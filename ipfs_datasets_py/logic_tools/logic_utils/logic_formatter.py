"""Logic formatting utilities for output generation."""

import json
from typing import Any, Dict, List, Union


def format_fol(formula: str, output_format: str = "symbolic", include_metadata: bool = True) -> Dict[str, Any]:
    result: Dict[str, Any] = {"fol_formula": formula, "format": output_format}

    if output_format == "prolog":
        result["prolog_form"] = convert_to_prolog_format(formula)
    elif output_format == "tptp":
        result["tptp_form"] = convert_to_tptp_format(formula)
    elif output_format == "json":
        result["structured_form"] = parse_fol_to_json(formula)

    if include_metadata:
        result["metadata"] = extract_fol_metadata(formula)

    return result


def format_deontic(
    formula: str,
    norm_type: str,
    output_format: str = "symbolic",
    include_metadata: bool = True,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"deontic_formula": formula, "norm_type": norm_type, "format": output_format}

    if output_format == "defeasible":
        result["defeasible_form"] = convert_to_defeasible_format(formula, norm_type)
    elif output_format == "json":
        result["structured_form"] = parse_deontic_to_json(formula)

    if include_metadata:
        result["metadata"] = extract_deontic_metadata(formula, norm_type)

    return result


def format_output(
    formulas: List[Dict[str, Any]],
    summary: Dict[str, Any],
    output_format: str = "json",
) -> Union[Dict[str, Any], str]:
    if output_format == "json":
        return {
            "status": "success",
            "formulas": formulas,
            "summary": summary,
            "metadata": {"conversion_timestamp": get_timestamp(), "tool_version": "1.0.0"},
        }
    if output_format == "text":
        return format_text_output(formulas, summary)
    if output_format == "xml":
        return format_xml_output(formulas, summary)
    return {"error": f"Unsupported output format: {output_format}"}


def convert_to_prolog_format(fol_formula: str) -> str:
    import re

    universal_impl = re.search(r"∀(\w+)\s*\((\w+)\((\w+)\)\s*→\s*(\w+)\((\w+)\)\)", fol_formula)
    if universal_impl:
        var, pred1, var1, pred2, var2 = universal_impl.groups()
        return f"{pred2.lower()}({var.upper()}) :- {pred1.lower()}({var.upper()})."

    existential = re.search(r"∃(\w+)\s*(\w+)\((\w+)\)", fol_formula)
    if existential:
        var, pred, var2 = existential.groups()
        return f"{pred.lower()}(a)."

    return f"% {fol_formula}"


def convert_to_tptp_format(fol_formula: str) -> str:
    tptp = fol_formula
    tptp = tptp.replace("∀", "![")
    tptp = tptp.replace("∃", "?[")
    tptp = tptp.replace("∧", " & ")
    tptp = tptp.replace("∨", " | ")
    tptp = tptp.replace("→", " => ")
    tptp = tptp.replace("↔", " <=> ")
    tptp = tptp.replace("¬", "~")

    import re

    tptp = re.sub(r"(\![a-z]|\?[a-z])", r"\1]:", tptp)
    return f"fof(formula, axiom, {tptp})."


def convert_to_defeasible_format(deontic_formula: str, norm_type: str) -> str:
    if norm_type == "obligation":
        return f"obligatory({deontic_formula}) unless defeated."
    if norm_type == "permission":
        return f"permitted({deontic_formula}) unless forbidden."
    if norm_type == "prohibition":
        return f"forbidden({deontic_formula}) unless permitted."
    return f"norm({deontic_formula})."


def parse_fol_to_json(fol_formula: str) -> Dict[str, Any]:
    import re

    structure: Dict[str, Any] = {"quantifiers": [], "predicates": [], "variables": [], "operators": []}

    quantifiers = re.findall(r"([∀∃])([a-z])", fol_formula)
    for symbol, var in quantifiers:
        structure["quantifiers"].append(
            {"type": "universal" if symbol == "∀" else "existential", "variable": var, "symbol": symbol}
        )

    predicates = re.findall(r"([A-Z][a-zA-Z]*)\(([^)]+)\)", fol_formula)
    for name, args in predicates:
        structure["predicates"].append(
            {"name": name, "arity": len(args.split(",")), "arguments": args.split(",")}
        )

    variables = set(re.findall(r"\b([a-z])\b", fol_formula))
    structure["variables"] = list(variables)

    operators: List[Dict[str, Any]] = []
    if "∧" in fol_formula:
        operators.append({"type": "conjunction", "symbol": "∧"})
    if "∨" in fol_formula:
        operators.append({"type": "disjunction", "symbol": "∨"})
    if "→" in fol_formula:
        operators.append({"type": "implication", "symbol": "→"})
    if "¬" in fol_formula:
        operators.append({"type": "negation", "symbol": "¬"})

    structure["operators"] = operators
    return structure


def parse_deontic_to_json(deontic_formula: str) -> Dict[str, Any]:
    import re

    structure: Dict[str, Any] = {"deontic_operators": [], "predicates": [], "logical_structure": {}}

    deontic_ops = re.findall(r"([OPF])\(", deontic_formula)
    for op in deontic_ops:
        op_type = {"O": "obligation", "P": "permission", "F": "prohibition"}.get(op, "unknown")
        structure["deontic_operators"].append({"type": op_type, "symbol": op})

    logical_part = re.search(r"[OPF]\((.+)\)$", deontic_formula)
    if logical_part:
        structure["logical_structure"] = parse_fol_to_json(logical_part.group(1))

    return structure


def extract_fol_metadata(formula: str) -> Dict[str, Any]:
    import re

    metadata: Dict[str, Any] = {
        "complexity": "simple",
        "quantifier_count": 0,
        "predicate_count": 0,
        "operator_count": 0,
        "max_arity": 0,
    }

    metadata["quantifier_count"] = len(re.findall(r"[∀∃]", formula))

    predicates = re.findall(r"[A-Z][a-zA-Z]*\(([^)]+)\)", formula)
    metadata["predicate_count"] = len(predicates)
    if predicates:
        metadata["max_arity"] = max(len(args.split(",")) for args in predicates)

    metadata["operator_count"] = len(re.findall(r"[∧∨→↔¬]", formula))

    operator_count = metadata["operator_count"]
    quantifier_count = metadata["quantifier_count"]
    predicate_count = metadata["predicate_count"]

    total_complexity = operator_count + quantifier_count + predicate_count
    if total_complexity > 10:
        metadata["complexity"] = "complex"
    elif total_complexity > 5:
        metadata["complexity"] = "moderate"

    return metadata


def extract_deontic_metadata(formula: str, norm_type: str) -> Dict[str, Any]:
    metadata = extract_fol_metadata(formula)
    metadata["norm_type"] = norm_type
    metadata["deontic_operator"] = norm_type[:1].upper()
    return metadata


def get_timestamp() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def format_text_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Logic Conversion Results")
    lines.append("=" * 30)
    lines.append(f"Total formulas: {len(formulas)}")
    lines.append(f"Conversion rate: {summary.get('conversion_rate', 0.0):.2%}")
    lines.append("")

    for idx, formula in enumerate(formulas, start=1):
        lines.append(f"Formula {idx}:")
        lines.append(f"  Original: {formula.get('original_text', '')}")
        lines.append(f"  Logic: {formula.get('fol_formula') or formula.get('deontic_formula', '')}")
        lines.append("")

    return "\n".join(lines)


def format_xml_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    return json.dumps({"formulas": formulas, "summary": summary})

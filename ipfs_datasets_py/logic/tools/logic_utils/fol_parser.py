"""First-Order Logic parsing and formula generation utilities."""

import re
from typing import Any, Dict, List, Optional

from .predicate_extractor import extract_predicates, extract_logical_relations


def parse_quantifiers(text: str) -> List[Dict[str, Any]]:
    quantifiers: List[Dict[str, Any]] = []

    universal_patterns = [
        r"\b(?:all|every|each)\s+(\w+)",
        r"\b(?:any|everything|everyone)\b",
        r"\bfor\s+all\s+(\w+)",
    ]

    for pattern in universal_patterns:
        for match in re.finditer(pattern, text.lower()):
            quantifiers.append(
                {
                    "type": "universal",
                    "symbol": "∀",
                    "scope": match.group(1) if match.groups() else "x",
                    "position": match.span(),
                }
            )

    existential_patterns = [
        r"\b(?:some|there (?:is|are|exists?))\s+(\w+)",
        r"\b(?:something|someone|at least one)\b",
        r"\bthere (?:is|are) (?:a|an|some)\s+(\w+)",
    ]

    for pattern in existential_patterns:
        for match in re.finditer(pattern, text.lower()):
            quantifiers.append(
                {
                    "type": "existential",
                    "symbol": "∃",
                    "scope": match.group(1) if match.groups() else "x",
                    "position": match.span(),
                }
            )

    return quantifiers


def parse_logical_operators(text: str) -> List[Dict[str, Any]]:
    operators: List[Dict[str, Any]] = []

    and_patterns = [r"\band\b", r"\bboth\s+.+?\s+and\b", r"[,;]\s*(?=\w)"]
    for pattern in and_patterns:
        for match in re.finditer(pattern, text.lower()):
            operators.append({"type": "conjunction", "symbol": "∧", "position": match.span()})

    or_patterns = [r"\bor\b", r"\beither\s+.+?\s+or\b"]
    for pattern in or_patterns:
        for match in re.finditer(pattern, text.lower()):
            operators.append({"type": "disjunction", "symbol": "∨", "position": match.span()})

    impl_patterns = [r"\bif\s+.+?\s+then\b", r"\bimplies?\b", r"\btherefore\b", r"\bso\b", r"\bhence\b"]
    for pattern in impl_patterns:
        for match in re.finditer(pattern, text.lower()):
            operators.append({"type": "implication", "symbol": "→", "position": match.span()})

    neg_patterns = [r"\bnot\b", r"\bno\b", r"\bnone\b", r"\bnever\b", r"\bnothing\b"]
    for pattern in neg_patterns:
        for match in re.finditer(pattern, text.lower()):
            operators.append({"type": "negation", "symbol": "¬", "position": match.span()})

    return operators


def build_fol_formula(
    quantifiers: List[Dict[str, Any]],
    predicates: Dict[str, List[str]],
    operators: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
) -> str:
    if not relations:
        if predicates.get("nouns") and predicates.get("adjectives"):
            noun = predicates["nouns"][0]
            adj = predicates["adjectives"][0]
            return f"∀x ({noun}(x) → {adj}(x))"
        if predicates.get("nouns"):
            noun = predicates["nouns"][0]
            return f"∃x {noun}(x)"
        return "⊤"

    formulas: List[str] = []
    for relation in relations:
        if relation["type"] == "universal":
            subject = normalize_predicate_name(relation["subject"])
            predicate = normalize_predicate_name(relation["predicate"])
            formulas.append(f"∀x ({subject}(x) → {predicate}(x))")
        elif relation["type"] == "existential":
            subject = normalize_predicate_name(relation["subject"])
            predicate = normalize_predicate_name(relation["predicate"])
            formulas.append(f"∃x ({subject}(x) ∧ {predicate}(x))")
        elif relation["type"] == "implication":
            premise = parse_simple_predicate(relation["premise"])
            conclusion = parse_simple_predicate(relation["conclusion"])
            formulas.append(f"∀x ({premise} → {conclusion})")

    if len(formulas) == 1:
        return formulas[0]
    if len(formulas) > 1:
        return " ∧ ".join(f"({f})" for f in formulas)
    return "⊤"


def parse_fol(text: str) -> Dict[str, Any]:
    normalized = (text or "").strip()
    if not normalized:
        return {
            "fol_formula": "⊤",
            "quantifiers": [],
            "operators": [],
            "predicates": {},
            "relations": [],
            "validation": validate_fol_syntax("⊤"),
        }

    quantifiers = parse_quantifiers(normalized)
    operators = parse_logical_operators(normalized)
    predicates = extract_predicates(normalized)
    relations = extract_logical_relations(normalized)
    fol_formula = build_fol_formula(quantifiers, predicates, operators, relations)

    return {
        "fol_formula": fol_formula,
        "quantifiers": quantifiers,
        "operators": operators,
        "predicates": predicates,
        "relations": relations,
        "validation": validate_fol_syntax(fol_formula),
    }


def normalize_predicate_name(name: str) -> str:
    words = name.strip().split()
    filtered = [w for w in words if w.lower() not in ["the", "a", "an"]]
    return "".join(word.capitalize() for word in filtered) or "P"


def parse_simple_predicate(text: str) -> str:
    words = text.strip().split()
    if len(words) == 1:
        return f"{normalize_predicate_name(words[0])}(x)"
    predicate = words[-1] if words else "P"
    return f"{normalize_predicate_name(predicate)}(x)"


def validate_fol_syntax(formula: str) -> Dict[str, Any]:
    if not formula or not isinstance(formula, str):
        return {"valid": False, "errors": ["Formula is empty or not a string"]}

    errors: List[str] = []

    paren_balance = 0
    for ch in formula:
        if ch == "(":
            paren_balance += 1
        elif ch == ")":
            paren_balance -= 1
            if paren_balance < 0:
                errors.append("Unmatched closing parenthesis")
                break

    if paren_balance != 0:
        errors.append("Unbalanced parentheses")

    if "∀" in formula or "∃" in formula:
        if not re.search(r"[∀∃][a-z]", formula):
            errors.append("Quantifier missing variable")

    predicate_matches = re.findall(r"[A-Z][a-zA-Z]*\([^)]*\)", formula)
    if not predicate_matches and formula not in ["⊤", "⊥"]:
        errors.append("No valid predicate found")

    return {"valid": len(errors) == 0, "errors": errors}


def convert_to_prolog(fol_formula: str) -> str:
    from .logic_formatter import convert_to_prolog_format

    return convert_to_prolog_format(fol_formula)


def convert_to_tptp(fol_formula: str) -> str:
    from .logic_formatter import convert_to_tptp_format

    return convert_to_tptp_format(fol_formula)

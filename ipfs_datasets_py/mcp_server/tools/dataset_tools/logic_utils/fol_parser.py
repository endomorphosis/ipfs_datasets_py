# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/fol_parser.py
"""
First-Order Logic parsing and formula generation utilities.
"""
import re
from typing import List, Dict, Tuple, Any, Optional

from .predicate_extractor import extract_logical_relations, extract_predicates

def parse_quantifiers(text: str) -> List[Dict[str, Any]]:
    """
    Parse quantifier words and expressions from text.
    
    Args:
        text: Input text
        
    Returns:
        List of quantifier information dictionaries
    """
    quantifiers = []
    
    # Universal quantifiers
    universal_patterns = [
        r'\b(?:all|every|each)\s+(\w+)',
        r'\b(?:any|everything|everyone)\b',
        r'\bfor\s+all\s+(\w+)'
    ]
    
    for pattern in universal_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            quantifiers.append({
                "type": "universal",
                "symbol": "∀",
                "scope": match.group(1) if match.groups() else "x",
                "position": match.span()
            })
    
    # Existential quantifiers
    existential_patterns = [
        r'\b(?:some|there (?:is|are|exists?))\s+(\w+)',
        r'\b(?:something|someone|at least one)\b',
        r'\bthere (?:is|are) (?:a|an|some)\s+(\w+)'
    ]
    
    for pattern in existential_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            quantifiers.append({
                "type": "existential",
                "symbol": "∃",
                "scope": match.group(1) if match.groups() else "x",
                "position": match.span()
            })
    
    return quantifiers

def parse_logical_operators(text: str) -> List[Dict[str, Any]]:
    """
    Parse logical operators from text.
    
    Args:
        text: Input text
        
    Returns:
        List of logical operator information
    """
    operators = []
    
    # Conjunction (AND)
    and_patterns = [
        r'\band\b',
        r'\bboth\s+.+?\s+and\b',
        r'[,;]\s*(?=\w)'  # Comma separation often implies AND
    ]
    
    for pattern in and_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            operators.append({
                "type": "conjunction",
                "symbol": "∧",
                "position": match.span()
            })
    
    # Disjunction (OR)
    or_patterns = [
        r'\bor\b',
        r'\beither\s+.+?\s+or\b'
    ]
    
    for pattern in or_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            operators.append({
                "type": "disjunction", 
                "symbol": "∨",
                "position": match.span()
            })
    
    # Implication
    impl_patterns = [
        r'\bif\s+.+?\s+then\b',
        r'\bimplies?\b',
        r'\btherefore\b',
        r'\bso\b',
        r'\bhence\b'
    ]
    
    for pattern in impl_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            operators.append({
                "type": "implication",
                "symbol": "→",
                "position": match.span()
            })
    
    # Negation
    neg_patterns = [
        r'\bnot\b',
        r'\bno\b',
        r'\bnone\b',
        r'\bnever\b',
        r'\bnothing\b'
    ]
    
    for pattern in neg_patterns:
        matches = re.finditer(pattern, text.lower())
        for match in matches:
            operators.append({
                "type": "negation",
                "symbol": "¬",
                "position": match.span()
            })
    
    return operators

def build_fol_formula(
    quantifiers: List[Dict[str, Any]],
    predicates: Dict[str, List[str]],
    operators: List[Dict[str, Any]],
    relations: List[Dict[str, Any]]
) -> str:
    """
    Build a First-Order Logic formula from parsed components.
    
    Args:
        quantifiers: Parsed quantifier information
        predicates: Extracted predicates
        operators: Parsed logical operators
        relations: Extracted logical relations
        
    Returns:
        FOL formula string
    """
    if not relations:
        # Simple predicate formula
        if predicates.get("nouns") and predicates.get("adjectives"):
            noun = predicates["nouns"][0]
            adj = predicates["adjectives"][0]
            return f"∀x ({noun}(x) → {adj}(x))"
        elif predicates.get("nouns"):
            noun = predicates["nouns"][0]
            return f"∃x {noun}(x)"
        else:
            return "⊤"  # True formula as fallback
    
    formulas = []
    variables = ['x', 'y', 'z']
    
    for relation in relations:
        if relation["type"] == "universal":
            subject = normalize_predicate_name(relation["subject"])
            predicate = normalize_predicate_name(relation["predicate"])
            formula = f"∀x ({subject}(x) → {predicate}(x))"
            formulas.append(formula)
            
        elif relation["type"] == "existential":
            subject = normalize_predicate_name(relation["subject"])
            predicate = normalize_predicate_name(relation["predicate"])
            formula = f"∃x ({subject}(x) ∧ {predicate}(x))"
            formulas.append(formula)
            
        elif relation["type"] == "implication":
            premise = parse_simple_predicate(relation["premise"])
            conclusion = parse_simple_predicate(relation["conclusion"])
            formula = f"∀x ({premise} → {conclusion})"
            formulas.append(formula)
    
    # Combine multiple formulas with conjunction
    if len(formulas) == 1:
        return formulas[0]
    elif len(formulas) > 1:
        return " ∧ ".join(f"({f})" for f in formulas)
    else:
        return "⊤"


def parse_fol(text: str) -> Dict[str, Any]:
    """
    Parse natural language text into a simple FOL formula representation.

    Args:
        text: Natural language input

    Returns:
        Dictionary with FOL formula and extracted components
    """
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
    """Normalize predicate names for FOL."""
    # Remove articles and normalize capitalization
    words = name.strip().split()
    filtered = [w for w in words if w.lower() not in ['the', 'a', 'an']]
    return ''.join(word.capitalize() for word in filtered) or "P"

def parse_simple_predicate(text: str) -> str:
    """Parse a simple predicate expression."""
    # Extract main predicate from phrase
    words = text.strip().split()
    if len(words) == 1:
        return f"{normalize_predicate_name(words[0])}(x)"
    else:
        # Try to find main predicate word
        predicate = words[-1] if words else "P"
        return f"{normalize_predicate_name(predicate)}(x)"

def validate_fol_syntax(formula: str) -> Dict[str, Any]:
    """
    Validate the syntax of a FOL formula.
    
    Args:
        formula: FOL formula string
        
    Returns:
        Validation result dictionary
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": []
    }
    
    # Check balanced parentheses
    paren_count = formula.count('(') - formula.count(')')
    if paren_count != 0:
        result["valid"] = False
        result["errors"].append(f"Unbalanced parentheses: {paren_count} extra opening" if paren_count > 0 else f"{-paren_count} extra closing")
    
    # Check for valid quantifiers
    quantifier_pattern = r'[∀∃][a-z]'
    quantifiers = re.findall(quantifier_pattern, formula)
    if not quantifiers and any(op in formula for op in ['∀', '∃']):
        result["warnings"].append("Quantifiers found but may be malformed")
    
    # Check for valid predicates
    predicate_pattern = r'[A-Z][a-zA-Z]*\([a-z,\s]*\)'
    predicates = re.findall(predicate_pattern, formula)
    if not predicates and '(' in formula:
        result["warnings"].append("Predicate applications may be malformed")
    
    # Check for valid logical operators
    valid_operators = ['∧', '∨', '→', '↔', '¬']
    for char in formula:
        if char in ['&', '|', '->', '<->', '!', '~'] and char not in valid_operators:
            result["warnings"].append(f"Non-standard operator '{char}' found")
    
    return result

def convert_to_prolog(fol_formula: str) -> str:
    """
    Convert FOL formula to Prolog syntax.
    
    Args:
        fol_formula: FOL formula in symbolic notation
        
    Returns:
        Prolog clause string
    """
    # Simple conversion for basic patterns
    # This would be much more sophisticated in a full implementation
    
    # Universal implication: ∀x (P(x) → Q(x)) becomes Q(X) :- P(X).
    universal_impl_pattern = r'∀(\w+)\s*\((\w+)\((\w+)\)\s*→\s*(\w+)\((\w+)\)\)'
    match = re.match(universal_impl_pattern, fol_formula)
    if match:
        var, pred1, var1, pred2, var2 = match.groups()
        return f"{pred2.lower()}({var.upper()}) :- {pred1.lower()}({var.upper()})."
    
    # Simple existential: ∃x P(x) becomes P(a).
    existential_pattern = r'∃(\w+)\s*(\w+)\((\w+)\)'
    match = re.match(existential_pattern, fol_formula)
    if match:
        var, pred, var2 = match.groups()
        return f"{pred.lower()}(a)."
    
    # Default fallback
    return f"% Cannot convert: {fol_formula}"

def convert_to_tptp(fol_formula: str) -> str:
    """
    Convert FOL formula to TPTP syntax.
    
    Args:
        fol_formula: FOL formula in symbolic notation
        
    Returns:
        TPTP format string
    """
    # Convert symbols to TPTP syntax
    tptp_formula = fol_formula
    tptp_formula = tptp_formula.replace('∀', '![')
    tptp_formula = tptp_formula.replace('∃', '?[')
    tptp_formula = tptp_formula.replace('∧', ' & ')
    tptp_formula = tptp_formula.replace('∨', ' | ')
    tptp_formula = tptp_formula.replace('→', ' => ')
    tptp_formula = tptp_formula.replace('↔', ' <=> ')
    tptp_formula = tptp_formula.replace('¬', '~')
    
    # Add TPTP variable syntax
    tptp_formula = re.sub(r'([∀∃]\w+)', r'\1]:', tptp_formula)
    
    return f"fof(formula1, axiom, {tptp_formula})."

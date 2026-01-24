# ipfs_datasets_py/mcp_server/tools/dataset_tools/tests/test_logic_utils.py
"""
Tests for the logic utilities module.
"""
import anyio
from typing import Dict, Any, List

from ..logic_utils.predicate_extractor import extract_predicates, normalize_predicate, extract_logical_relations
from ..logic_utils.fol_parser import parse_quantifiers, parse_logical_operators, build_fol_formula, validate_fol_syntax
from ..logic_utils.deontic_parser import extract_normative_elements, build_deontic_formula, identify_obligations
from ..logic_utils.logic_formatter import format_fol, format_deontic

def test_predicate_extraction():
    """Test predicate extraction functionality."""
    
    text = "All cats are animals and some dogs are friendly"
    predicates = extract_predicates(text)
    
    assert isinstance(predicates, dict)
    assert "nouns" in predicates
    assert "verbs" in predicates
    assert "adjectives" in predicates
    
    # Test predicate normalization
    normalized = normalize_predicate("the big cat")
    assert isinstance(normalized, str)
    assert len(normalized) > 0
    assert normalized[0].isupper()  # Should start with uppercase
    
    # Test logical relations extraction
    relations = extract_logical_relations("If all cats are animals then some cats are pets")
    assert isinstance(relations, list)

def test_fol_parsing():
    """Test First-Order Logic parsing utilities."""
    
    text = "All students study hard and some teachers are helpful"
    
    # Test quantifier parsing
    quantifiers = parse_quantifiers(text)
    assert isinstance(quantifiers, list)
    
    # Should find universal quantifier "All"
    universal_found = any(q["type"] == "universal" for q in quantifiers)
    existential_found = any(q["type"] == "existential" for q in quantifiers)
    
    # Test logical operators parsing
    operators = parse_logical_operators(text)
    assert isinstance(operators, list)
    
    # Should find "and" operator
    and_found = any(op["type"] == "conjunction" for op in operators)
    
    # Test FOL formula building
    predicates = extract_predicates(text)
    relations = extract_logical_relations(text)
    
    formula = build_fol_formula(quantifiers, predicates, operators, relations)
    assert isinstance(formula, str)
    assert len(formula) > 0
    
    # Test formula validation
    validation = validate_fol_syntax(formula)
    assert isinstance(validation, dict)
    assert "valid" in validation
    assert "errors" in validation

def test_deontic_parsing():
    """Test deontic logic parsing utilities."""
    
    legal_text = "All employees must complete safety training annually"
    
    # Test normative elements extraction
    elements = extract_normative_elements(legal_text, "regulation")
    assert isinstance(elements, list)
    
    if elements:
        element = elements[0]
        assert isinstance(element, dict)
        assert "norm_type" in element
        assert "deontic_operator" in element
        assert "text" in element
        
        # Test deontic formula building
        formula = build_deontic_formula(element)
        assert isinstance(formula, str)
        assert len(formula) > 0
        assert element["deontic_operator"] in formula

def test_fol_formatting():
    """Test FOL formatting utilities."""
    
    formula = "∀x (Cat(x) → Animal(x))"
    
    # Test symbolic format
    formatted = format_fol(formula, output_format='symbolic')
    assert isinstance(formatted, dict)
    assert "fol_formula" in formatted
    assert formatted["fol_formula"] == formula
    
    # Test with metadata
    formatted_meta = format_fol(formula, include_metadata=True)
    assert "metadata" in formatted_meta

def test_deontic_formatting():
    """Test deontic logic formatting utilities."""
    
    formula = "O(∀x (Employee(x) → Training(x)))"
    norm_type = "obligation"
    
    # Test symbolic format
    formatted = format_deontic(formula, norm_type, output_format='symbolic')
    assert isinstance(formatted, dict)
    assert "deontic_formula" in formatted
    assert "norm_type" in formatted
    assert formatted["norm_type"] == norm_type
    
    # Test with metadata
    formatted_meta = format_deontic(formula, norm_type, include_metadata=True)
    assert "metadata" in formatted_meta

def test_normative_structure_analysis():
    """Test normative structure identification."""
    
    # Create sample normative elements
    elements = [
        {
            "text": "Employees must clock in",
            "norm_type": "obligation",
            "deontic_operator": "O",
            "subject": ["employees"],
            "action": ["clock in"]
        },
        {
            "text": "Managers may approve overtime",
            "norm_type": "permission", 
            "deontic_operator": "P",
            "subject": ["managers"],
            "action": ["approve overtime"]
        },
        {
            "text": "Workers cannot smoke indoors",
            "norm_type": "prohibition",
            "deontic_operator": "F", 
            "subject": ["workers"],
            "action": ["smoke indoors"]
        }
    ]
    
    # Test obligation identification
    structure = identify_obligations(elements)
    assert isinstance(structure, dict)
    assert "obligations" in structure
    assert "permissions" in structure
    assert "prohibitions" in structure
    
    # Check that elements are properly categorized
    assert len(structure["obligations"]) >= 1
    assert len(structure["permissions"]) >= 1
    assert len(structure["prohibitions"]) >= 1

def test_formula_syntax_validation():
    """Test syntax validation for logic formulas."""
    
    # Test valid FOL formula
    valid_formula = "∀x (Cat(x) → Animal(x))"
    validation = validate_fol_syntax(valid_formula)
    assert validation["valid"] == True
    assert len(validation["errors"]) == 0
    
    # Test invalid formula (unbalanced parentheses)
    invalid_formula = "∀x (Cat(x) → Animal(x)"
    validation_invalid = validate_fol_syntax(invalid_formula)
    assert validation_invalid["valid"] == False
    assert len(validation_invalid["errors"]) > 0

def test_logical_relations_extraction():
    """Test extraction of logical relationships."""
    
    # Test implication
    impl_text = "If it is raining then the ground is wet"
    relations = extract_logical_relations(impl_text)
    
    impl_relations = [r for r in relations if r["type"] == "implication"]
    assert len(impl_relations) > 0
    
    # Test universal quantification
    univ_text = "All birds have wings"
    relations_univ = extract_logical_relations(univ_text)
    
    univ_relations = [r for r in relations_univ if r["type"] == "universal"]
    assert len(univ_relations) > 0

def test_predicate_normalization_edge_cases():
    """Test edge cases in predicate normalization."""
    
    # Test empty string
    normalized_empty = normalize_predicate("")
    assert isinstance(normalized_empty, str)
    assert len(normalized_empty) > 0  # Should return default predicate
    
    # Test string with articles
    normalized_articles = normalize_predicate("the big red car")
    assert "The" not in normalized_articles  # Articles should be removed
    assert normalized_articles[0].isupper()  # Should start with uppercase
    
    # Test single word
    normalized_single = normalize_predicate("cat")
    assert normalized_single == "Cat"

if __name__ == "__main__":
    print("Running logic utilities tests...")
    
    test_predicate_extraction()
    print("✓ Predicate extraction test passed")
    
    test_fol_parsing()
    print("✓ FOL parsing test passed")
    
    test_deontic_parsing() 
    print("✓ Deontic parsing test passed")
    
    test_fol_formatting()
    print("✓ FOL formatting test passed")
    
    test_deontic_formatting()
    print("✓ Deontic formatting test passed")
    
    test_normative_structure_analysis()
    print("✓ Normative structure analysis test passed")
    
    test_formula_syntax_validation()
    print("✓ Formula syntax validation test passed")
    
    test_logical_relations_extraction()
    print("✓ Logical relations extraction test passed")
    
    test_predicate_normalization_edge_cases()
    print("✓ Predicate normalization edge cases test passed")
    
    print("All logic utilities tests completed successfully!")

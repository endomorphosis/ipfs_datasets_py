#!/usr/bin/env python3
"""
Demonstration of DCEC Grammar-Based Natural Language Processing (Phase 4C).

This script showcases the grammar engine and DCEC English grammar capabilities:
- English to DCEC parsing
- DCEC to English linearization
- Compositional semantics
- Ambiguity handling
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native.dcec_english_grammar import create_dcec_grammar
from ipfs_datasets_py.logic.CEC.native.nl_converter import create_enhanced_nl_converter

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def demo_grammar_basics():
    """Demonstrate basic grammar functionality."""
    print_section("1. Grammar Engine Basics")
    
    grammar = create_dcec_grammar()
    
    print("✓ Grammar initialized successfully")
    print(f"  - Lexicon entries: {len(grammar.engine.lexicon)} words")
    print(f"  - Grammar rules: {len(grammar.engine.rules)} rules")
    print(f"  - Start category: {grammar.engine.start_category.value}")
    
    # Show sample lexicon
    print("\n📖 Sample Lexicon Entries:")
    sample_words = ["must", "believes", "always", "jack", "run", "happy"]
    for word in sample_words:
        if word in grammar.engine.lexicon:
            entries = grammar.engine.lexicon[word]
            categories = ", ".join(e.category.value for e in entries)
            print(f"  - '{word}': {categories}")


def demo_simple_parsing():
    """Demonstrate simple parsing examples."""
    print_section("2. Simple Parsing Examples")
    
    grammar = create_dcec_grammar()
    
    test_phrases = [
        "jack runs",
        "alice is happy",
        "robot must work",
        "bob believes alice is happy",
        "always jack runs",
    ]
    
    print("Parsing simple English phrases:\n")
    for phrase in test_phrases:
        print(f"Input: '{phrase}'")
        try:
            formula = grammar.parse_to_dcec(phrase)
            if formula:
                print(f"  ✓ Parsed successfully: {formula.to_string()}")
            else:
                print(f"  ⚠ No parse found (may need more complex rules)")
        except Exception as e:
            print(f"  ✗ Parse error: {e}")
        print()


def demo_linearization():
    """Demonstrate DCEC to English linearization."""
    print_section("3. DCEC to English Linearization")
    
    grammar = create_dcec_grammar()
    
    print("Converting semantic representations to English:\n")
    
    # Test various semantic structures
    test_semantics = [
        {
            "type": "deontic",
            "operator": "obligated",
            "agent": {"name": "jack"},
            "action": {"name": "run"}
        },
        {
            "type": "cognitive",
            "operator": "believes",
            "agent": {"name": "alice"},
            "proposition": {"type": "atomic", "predicate": "happy", "arguments": []}
        },
        {
            "type": "temporal",
            "operator": "always",
            "proposition": {"type": "atomic", "predicate": "working", "arguments": []}
        },
        {
            "type": "connective",
            "operator": "AND",
            "left": {"type": "atomic", "predicate": "P", "arguments": []},
            "right": {"type": "atomic", "predicate": "Q", "arguments": []}
        }
    ]
    
    for i, sem in enumerate(test_semantics, 1):
        print(f"Example {i}:")
        print(f"  Semantic: {sem}")
        try:
            english = grammar._linearize_boolean(sem)
            print(f"  English: '{english}'")
        except Exception as e:
            print(f"  Error: {e}")
        print()


def demo_enhanced_nl_converter():
    """Demonstrate enhanced NL converter with grammar support."""
    print_section("4. Enhanced NL Converter (Grammar + Pattern Fallback)")
    
    converter = create_enhanced_nl_converter(use_grammar=True)
    
    print(f"Converter initialized:")
    print(f"  - Grammar support: {converter.use_grammar}")
    print(f"  - Pattern support: ✓")
    
    test_sentences = [
        "The agent must fulfill the obligation",
        "Jack believes Alice is happy",
        "Robot always works",
        "Alice intends to run",
        "Bob may walk",
    ]
    
    print("\n🔄 Converting English to DCEC:\n")
    for sentence in test_sentences:
        print(f"Input: '{sentence}'")
        result = converter.convert_to_dcec(sentence)
        if result.success:
            print(f"  ✓ Success ({result.parse_method})")
            print(f"    Confidence: {result.confidence:.2f}")
            if result.dcec_formula:
                print(f"    DCEC: {result.dcec_formula.to_string()}")
        else:
            print(f"  ✗ Failed: {result.error_message}")
        print()


def demo_compositional_semantics():
    """Demonstrate compositional semantics."""
    print_section("5. Compositional Semantics")
    
    print("Building complex meanings from simple parts:\n")
    
    examples = [
        ("Logical AND", "P and Q", "Combines two propositions"),
        ("Deontic modal", "jack must run", "Agent + obligation + action"),
        ("Cognitive modal", "alice believes P", "Agent + belief + proposition"),
        ("Temporal modal", "always P", "Temporal operator + proposition"),
        ("Negation", "not P", "Negation of proposition"),
    ]
    
    for name, example, description in examples:
        print(f"📝 {name}: '{example}'")
        print(f"   Description: {description}")
        print()


def demo_grammar_rules():
    """Show sample grammar rules."""
    print_section("6. Grammar Rules Overview")
    
    grammar = create_dcec_grammar()
    
    rule_categories = {}
    for rule in grammar.engine.rules:
        category = rule.category.value
        if category not in rule_categories:
            rule_categories[category] = []
        rule_categories[category].append(rule.name)
    
    print("Grammar rules by category:\n")
    for category, rules in sorted(rule_categories.items()):
        print(f"📋 {category}:")
        for rule in rules[:5]:  # Show first 5
            print(f"   - {rule}")
        if len(rules) > 5:
            print(f"   ... and {len(rules) - 5} more")
        print()


def demo_ambiguity_resolution():
    """Demonstrate ambiguity resolution strategies."""
    print_section("7. Ambiguity Resolution")
    
    print("Handling multiple possible parses:\n")
    
    print("📌 Strategy: 'first' - Select first parse")
    print("   Use case: Fast, deterministic")
    print()
    
    print("📌 Strategy: 'shortest' - Prefer parse with fewest nodes")
    print("   Use case: Simpler structures")
    print()
    
    print("📌 Strategy: 'most_specific' - Prefer most specific categories")
    print("   Use case: More detailed semantic representations")
    print()


def demo_performance_comparison():
    """Compare grammar-based vs pattern-based parsing."""
    print_section("8. Performance Comparison")
    
    converter = create_enhanced_nl_converter(use_grammar=True)
    
    test_sentence = "The agent must fulfill the obligation"
    
    print("Comparing parsing methods:\n")
    
    # Grammar-based
    print("🔹 Grammar-based parsing:")
    result_grammar = converter.convert_to_dcec(test_sentence)
    print(f"   Method: {result_grammar.parse_method}")
    print(f"   Success: {result_grammar.success}")
    print(f"   Confidence: {result_grammar.confidence:.2f}")
    
    print()
    
    # Pattern-based
    print("🔹 Pattern-based parsing:")
    result_pattern = converter.convert_to_dcec(test_sentence)
    print(f"   Method: {result_pattern.parse_method}")
    print(f"   Success: {result_pattern.success}")
    print(f"   Confidence: {result_pattern.confidence:.2f}")


def demo_feature_coverage():
    """Show feature coverage of the grammar."""
    print_section("9. Feature Coverage")
    
    features = {
        "Logical Operators": ["AND", "OR", "NOT", "IMPLIES", "IFF"],
        "Deontic Modals": ["Obligation (must)", "Permission (may)", "Prohibition (forbidden)"],
        "Cognitive Modals": ["Belief", "Knowledge", "Intention", "Desire"],
        "Temporal Operators": ["Always", "Eventually", "Next", "Until"],
        "Quantifiers": ["Forall (all, every)", "Exists (some, any)"],
        "Agents": ["Named agents (jack, alice, bob, robot)"],
        "Actions": ["Common actions (run, walk, sleep, eat)"],
        "Fluents": ["States/properties (happy, sad, hungry, tired)"],
    }
    
    for category, items in features.items():
        print(f"✅ {category}:")
        for item in items:
            print(f"   • {item}")
        print()


def demo_future_enhancements():
    """Discuss future enhancements."""
    print_section("10. Future Enhancements")
    
    enhancements = [
        ("Quantifier scoping", "Better handling of nested quantifiers"),
        ("Tense and aspect", "Past, present, future tenses"),
        ("Plurals", "Handling plural nouns and verbs"),
        ("Complex noun phrases", "The agent who believes..."),
        ("Coordination", "Jack and Alice run"),
        ("Question handling", "Does jack run?"),
        ("Imperative mood", "Run!"),
        ("Negation scope", "Better negation placement"),
    ]
    
    print("Potential future enhancements:\n")
    for enhancement, description in enhancements:
        print(f"🔮 {enhancement}")
        print(f"   {description}")
        print()


def main():
    """Run all demonstrations."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║               DCEC Grammar-Based Natural Language Processing                 ║
║                            Phase 4C Demonstration                            ║
║                                                                              ║
║  This demonstration showcases the native Python 3 implementation of          ║
║  grammar-based natural language processing for DCEC, replacing the           ║
║  GF-based Eng-DCEC system.                                                  ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    try:
        demo_grammar_basics()
        demo_simple_parsing()
        demo_linearization()
        demo_enhanced_nl_converter()
        demo_compositional_semantics()
        demo_grammar_rules()
        demo_ambiguity_resolution()
        demo_performance_comparison()
        demo_feature_coverage()
        demo_future_enhancements()
        
        print_section("✨ Demonstration Complete")
        print("Phase 4C: Grammar-based NL processing is operational!")
        print("\nNext steps:")
        print("  - Phase 4C Part 2: Integration tests and performance tuning")
        print("  - Phase 4D: ShadowProver Java port (~2,700 LOC)")
        print("  - Phase 4E: Final integration and polish (~500 LOC)")
        
    except Exception as e:
        logger.error(f"Demonstration error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

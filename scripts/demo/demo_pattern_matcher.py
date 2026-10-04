#!/usr/bin/env python3
"""
Demo script for TDFOL Pattern Matcher (Phase 7 Week 2)

This script demonstrates the pattern matching functionality, showing how
the system identifies legal and deontic patterns in natural language text.

Usage:
    python demo_pattern_matcher.py
"""

import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def print_separator(title: str = ""):
    """Print a visual separator."""
    if title:
        print(f"\n{'=' * 70}")
        print(f" {title}")
        print('=' * 70)
    else:
        print('-' * 70)


def demonstrate_pattern_matcher():
    """Demonstrate the pattern matcher functionality."""
    
    try:
        from ipfs_datasets_py.logic.TDFOL.nl import PatternMatcher, PatternType
    except ImportError as e:
        logger.error("Failed to import PatternMatcher")
        logger.error("Make sure spaCy is installed: pip install ipfs_datasets_py[knowledge_graphs]")
        logger.error(f"Error: {e}")
        return False
    
    print_separator("TDFOL Pattern Matcher Demo")
    print("\nPhase 7 Week 2: Pattern Matching with 45+ Legal/Deontic Patterns")
    print("Identifies universal quantification, obligations, permissions,")
    print("prohibitions, temporal expressions, and conditionals\n")
    
    # Initialize matcher
    try:
        print("Initializing Pattern Matcher...")
        matcher = PatternMatcher()
        print("✓ Pattern Matcher initialized successfully")
        
        # Show pattern counts
        counts = matcher.get_pattern_count()
        print(f"\nLoaded {sum(counts.values())} patterns:")
        for pattern_type, count in counts.items():
            print(f"  • {pattern_type.value}: {count} patterns")
        print()
    except (ImportError, OSError) as e:
        logger.error(f"Failed to initialize matcher: {e}")
        logger.info("If spaCy model not found, download with:")
        logger.info("  python -m spacy download en_core_web_sm")
        return False
    
    # Test examples - various legal/deontic patterns
    examples = [
        ("Universal Quantification", "All contractors must pay taxes within 30 days."),
        ("Obligation", "The contractor shall deliver goods by the deadline."),
        ("Permission", "Employees may request vacation time after one year."),
        ("Prohibition", "Contractors must not disclose confidential information."),
        ("Temporal", "Payment must be made within 30 days of invoice."),
        ("Conditional", "If the work is completed, then payment shall be made."),
        ("Complex", "Every employee is required to comply with safety regulations unless exempted."),
        ("Multiple Patterns", "All parties must always comply and may not violate the terms."),
    ]
    
    for category, text in examples:
        print_separator(f"{category} Example")
        print(f"Input: {text}\n")
        
        # Match patterns
        try:
            matches = matcher.match(text, min_confidence=0.5)
            
            if matches:
                print(f"Found {len(matches)} pattern(s):\n")
                for i, match in enumerate(matches, 1):
                    print(f"  {i}. Pattern: {match.pattern.name}")
                    print(f"     Type: {match.pattern.type.value}")
                    print(f"     Text: \"{match.text}\"")
                    print(f"     Confidence: {match.confidence:.2f}")
                    
                    if match.entities:
                        print(f"     Entities:")
                        for key, value in match.entities.items():
                            print(f"       - {key}: {value}")
                    
                    print()
            else:
                print("  No patterns matched (try lowering confidence threshold)\n")
        
        except Exception as e:
            logger.error(f"Error matching patterns: {e}")
            import traceback
            traceback.print_exc()
    
    # Show pattern type summary
    print_separator("Pattern Type Examples")
    print("\n1. Universal Quantification:")
    print("   • All agents must/shall/may action")
    print("   • Every agent verb")
    print("   • Any agent must/may action")
    
    print("\n2. Obligations:")
    print("   • Agent must action")
    print("   • Agent shall action")
    print("   • Agent is required to action")
    
    print("\n3. Permissions:")
    print("   • Agent may action")
    print("   • Agent can action")
    print("   • Agent is allowed to action")
    
    print("\n4. Prohibitions:")
    print("   • Agent must not action")
    print("   • Agent shall not action")
    print("   • Agent is forbidden to action")
    
    print("\n5. Temporal:")
    print("   • Always action")
    print("   • Within/after/before N days")
    print("   • Eventually action")
    
    print("\n6. Conditionals:")
    print("   • If condition then consequence")
    print("   • When event action")
    print("   • Provided that condition")
    
    # Summary
    print_separator("Summary")
    print("\n✓ Phase 7 Week 2 Implementation Complete!")
    print("\nFeatures Demonstrated:")
    print(f"  ✓ {sum(counts.values())} patterns across 6 categories")
    print("  ✓ Universal quantification (all, every, any)")
    print("  ✓ Obligations (must, shall, required to)")
    print("  ✓ Permissions (may, can, allowed to)")
    print("  ✓ Prohibitions (must not, forbidden to)")
    print("  ✓ Temporal expressions (always, within, until)")
    print("  ✓ Conditionals (if-then, when, provided that)")
    print("  ✓ Entity extraction (agents, actions, modalities)")
    print("  ✓ Confidence scoring")
    
    print("\nNext Steps:")
    print("  - Week 3: Implement formula generator (NL → TDFOL conversion)")
    print("  - Week 3: Implement context resolver")
    print("  - Week 4: Complete integration and testing")
    print("\n")
    
    return True


def main():
    """Main entry point."""
    success = demonstrate_pattern_matcher()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

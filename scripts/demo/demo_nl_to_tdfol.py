#!/usr/bin/env python3
"""
Demo script for Complete NL → TDFOL Pipeline (Phase 7 Weeks 1-3)

This script demonstrates the complete natural language to TDFOL conversion
pipeline, integrating:
- Week 1: NL Preprocessing (entity recognition, temporal extraction)
- Week 2: Pattern Matching (45 legal/deontic patterns)
- Week 3: Formula Generation (NL → TDFOL formulas)
- Week 3: Context Resolution (cross-sentence tracking)

Usage:
    python demo_nl_to_tdfol.py
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


def demonstrate_nl_to_tdfol():
    """Demonstrate the complete NL → TDFOL pipeline."""
    
    try:
        from ipfs_datasets_py.logic.TDFOL.nl import (
            NLPreprocessor,
            PatternMatcher,
            FormulaGenerator,
            ContextResolver,
        )
    except ImportError as e:
        logger.error("Failed to import NL processing components")
        logger.error(f"Error: {e}")
        return False
    
    print_separator("Complete NL → TDFOL Pipeline Demo")
    print("\nPhase 7 Weeks 1-3: Natural Language to TDFOL Conversion")
    print("Demonstrating the full pipeline from text to formal logic\n")
    
    # Initialize components
    try:
        print("Initializing NL processing pipeline...")
        preprocessor = NLPreprocessor()
        matcher = PatternMatcher()
        generator = FormulaGenerator()
        resolver = ContextResolver()
        print("✓ All components initialized successfully\n")
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        return False
    
    # Example texts
    examples = [
        {
            "title": "Simple Obligation",
            "text": "All contractors must pay taxes."
        },
        {
            "title": "Permission with Temporal",
            "text": "Employees may request vacation time after one year."
        },
        {
            "title": "Prohibition",
            "text": "Contractors must not disclose confidential information."
        },
        {
            "title": "Complex with Temporal",
            "text": "Every contractor shall always comply with safety regulations."
        },
        {
            "title": "Multi-sentence with Context",
            "text": "Contractors must submit reports. They shall file within 30 days."
        },
    ]
    
    for i, example in enumerate(examples, 1):
        print_separator(f"Example {i}: {example['title']}")
        text = example['text']
        print(f"Input: {text}\n")
        
        try:
            # Step 1: Preprocess
            print("Step 1: Preprocessing")
            doc = preprocessor.process(text)
            print(f"  • Sentences: {len(doc.sentences)}")
            print(f"  • Entities: {len(doc.entities)}")
            if doc.entities:
                for entity in doc.entities[:3]:  # Show first 3
                    print(f"    - {entity.text} ({entity.type.value})")
            if doc.modalities:
                print(f"  • Modalities: {doc.modalities}")
            if doc.temporal:
                print(f"  • Temporal: {[t.text for t in doc.temporal]}")
            print()
            
            # Step 2: Pattern Matching
            print("Step 2: Pattern Matching")
            matches = matcher.match(text)
            print(f"  • Patterns found: {len(matches)}")
            for match in matches[:3]:  # Show first 3
                print(f"    - {match.pattern.type.value}: \"{match.text}\"")
                print(f"      Confidence: {match.confidence:.2f}")
                if match.entities:
                    print(f"      Entities: {match.entities}")
            print()
            
            # Step 3: Build Context
            print("Step 3: Context Resolution")
            context = resolver.build_context(doc, sentence_id=0)
            print(f"  • Entities in context: {len(context.entities)}")
            for entity_name in list(context.entities.keys())[:3]:
                entity = context.entities[entity_name]
                print(f"    - {entity.name} ({entity.type})")
            
            # Check for references
            resolutions = resolver.resolve_references(doc, context)
            if resolutions:
                print(f"  • References resolved: {resolutions}")
            print()
            
            # Step 4: Formula Generation
            print("Step 4: Formula Generation")
            formulas = generator.generate_from_matches(matches, context)
            print(f"  • Formulas generated: {len(formulas)}")
            for formula in formulas[:3]:  # Show first 3
                print(f"\n    Formula: {formula.formula_string}")
                print(f"    Type: {formula.metadata.get('type', 'unknown')}")
                print(f"    Confidence: {formula.confidence:.2f}")
                if formula.entities:
                    print(f"    Entities: {formula.entities}")
            
        except Exception as e:
            logger.error(f"Error processing example: {e}")
            import traceback
            traceback.print_exc()
        
        print()
    
    # Summary
    print_separator("Pipeline Summary")
    print("\n✓ Phase 7 Weeks 1-3 Implementation Complete!")
    
    print("\nPipeline Stages:")
    print("  1. Preprocessing:")
    print("     • Sentence splitting")
    print("     • Entity recognition (agents, actions, objects)")
    print("     • Temporal expression extraction")
    print("     • Modal operator identification")
    
    print("\n  2. Pattern Matching:")
    print("     • 45 patterns across 6 categories")
    print("     • Universal quantification, obligations, permissions")
    print("     • Prohibitions, temporal, conditionals")
    print("     • Confidence scoring")
    
    print("\n  3. Context Resolution:")
    print("     • Cross-sentence entity tracking")
    print("     • Pronoun resolution")
    print("     • Coreference handling")
    
    print("\n  4. Formula Generation:")
    print("     • Pattern → TDFOL formula conversion")
    print("     • Universal: ∀x.(Agent(x) → ...)")
    print("     • Deontic: O(...), P(...), F(...)")
    print("     • Temporal: □(...), ◊(...), X(...)")
    print("     • Conditional: ... → ...")
    
    print("\nFormula Examples:")
    print("  • \"All contractors must pay taxes\"")
    print("    → ∀x.(Contractor(x) → O(PayTaxes(x)))")
    print("\n  • \"Contractor must deliver goods\"")
    print("    → O(DeliverGoods(contractor))")
    print("\n  • \"Employees may request vacation\"")
    print("    → P(RequestVacation(employees))")
    print("\n  • \"Must not disclose information\"")
    print("    → F(DiscloseInformation(contractor))")
    print("\n  • \"Must always comply\"")
    print("    → □(O(Comply()))")
    
    print("\nNext Steps:")
    print("  - Week 4: End-to-end integration and testing")
    print("  - Week 4: 80%+ accuracy validation")
    print("  - Week 4: Complete Phase 7 documentation")
    print("\n")
    
    return True


def main():
    """Main entry point."""
    success = demonstrate_nl_to_tdfol()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

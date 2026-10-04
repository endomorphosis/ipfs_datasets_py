#!/usr/bin/env python3
"""
Demo script for TDFOL Natural Language Preprocessor (Phase 7)

This script demonstrates the basic functionality of the NL preprocessor,
showing how it extracts entities, temporal expressions, and modal operators
from natural language text.

Usage:
    python demo_nl_preprocessor.py
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


def demonstrate_preprocessor():
    """Demonstrate the NL preprocessor functionality."""
    
    try:
        from ipfs_datasets_py.logic.TDFOL.nl import NLPreprocessor
    except ImportError as e:
        logger.error("Failed to import NLPreprocessor")
        logger.error("Make sure spaCy is installed: pip install ipfs_datasets_py[knowledge_graphs]")
        logger.error(f"Error: {e}")
        return False
    
    print_separator("TDFOL Natural Language Preprocessor Demo")
    print("\nPhase 7: Natural Language Processing Implementation")
    print("Week 1 Deliverable: NL Preprocessor with Entity Recognition\n")
    
    # Initialize preprocessor
    try:
        print("Initializing NL Preprocessor with spaCy...")
        preprocessor = NLPreprocessor()
        print("✓ Preprocessor initialized successfully\n")
    except (ImportError, OSError) as e:
        logger.error(f"Failed to initialize preprocessor: {e}")
        logger.info("If spaCy model not found, download with:")
        logger.info("  python -m spacy download en_core_web_sm")
        return False
    
    # Test examples
    examples = [
        "All contractors must pay taxes within 30 days.",
        "Alice must deliver the document to Bob.",
        "Contractors shall always comply with safety regulations.",
        "Every employee may request vacation time after one year.",
        "The company shall not disclose confidential information.",
    ]
    
    for i, text in enumerate(examples, 1):
        print_separator(f"Example {i}")
        print(f"Input: {text}\n")
        
        # Process text
        try:
            doc = preprocessor.process(text)
            
            # Show results
            print(f"Sentences: {len(doc.sentences)}")
            for j, sent in enumerate(doc.sentences, 1):
                print(f"  {j}. {sent}")
            
            print(f"\nEntities: {len(doc.entities)}")
            agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
            
            if agents:
                print(f"  Agents: {[e.text for e in agents]}")
            if actions:
                print(f"  Actions: {[e.lemma or e.text for e in actions]}")
            if objects:
                print(f"  Objects: {[e.text for e in objects]}")
            
            if doc.temporal:
                print(f"\nTemporal Expressions: {len(doc.temporal)}")
                for temp in doc.temporal:
                    print(f"  - {temp.text} (type: {temp.type})")
            
            if doc.modalities:
                print(f"\nModal Operators: {doc.modalities}")
            
            # Show statistics
            print(f"\nStatistics:")
            for key, value in doc.metadata.items():
                print(f"  {key}: {value}")
            
        except Exception as e:
            logger.error(f"Error processing text: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print_separator("Summary")
    print("\n✓ Phase 7 Week 1 Implementation Complete!")
    print("\nFeatures Demonstrated:")
    print("  ✓ Sentence splitting")
    print("  ✓ Entity recognition (agents, actions, objects)")
    print("  ✓ Temporal expression extraction")
    print("  ✓ Modal operator identification")
    print("  ✓ Dependency parsing")
    print("\nNext Steps:")
    print("  - Week 2: Implement pattern matcher (20+ patterns)")
    print("  - Week 3: Implement formula generator")
    print("  - Week 4: Complete integration and testing")
    print("\n")
    
    return True


def main():
    """Main entry point."""
    success = demonstrate_preprocessor()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

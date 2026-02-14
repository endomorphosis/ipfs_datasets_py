"""
Interactive FOL Constructor Utilities

This module provides utility functions and helpers for the Interactive
FOL Constructor system, including factory functions and demo/testing utilities.

Extracted from interactive_fol_constructor.py to improve modularity.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interactive_fol_constructor import InteractiveFOLConstructor


def create_interactive_session(domain: str = "general", **kwargs) -> "InteractiveFOLConstructor":
    """
    Factory function to create an interactive FOL constructor session.
    
    This is the recommended way to create a new InteractiveFOLConstructor
    instance, providing a clean API for session creation.
    
    Args:
        domain: Domain of knowledge (e.g., "mathematics", "legal", "general")
        **kwargs: Additional parameters for InteractiveFOLConstructor:
            - confidence_threshold: float (default: 0.6)
            - enable_consistency_checking: bool (default: True)
            
    Returns:
        InteractiveFOLConstructor instance ready for use
        
    Example:
        >>> session = create_interactive_session(
        ...     domain="legal",
        ...     confidence_threshold=0.7
        ... )
        >>> result = session.add_statement("All citizens have rights")
    """
    from .interactive_fol_constructor import InteractiveFOLConstructor
    return InteractiveFOLConstructor(domain=domain, **kwargs)


def demo_interactive_session() -> "InteractiveFOLConstructor":
    """
    Demonstrate the interactive FOL constructor with example usage.
    
    This function provides a complete demonstration of the system's
    capabilities, including statement addition, analysis, consistency
    checking, and statistics reporting.
    
    Returns:
        The InteractiveFOLConstructor instance used in the demo
        
    Example Usage:
        >>> constructor = demo_interactive_session()
        Interactive FOL Constructor Demo
        ========================================
        Added: All cats are animals
        FOL: ∀x(Cat(x) → Animal(x))
        Confidence: 0.92
        ...
    """
    print("Interactive FOL Constructor Demo")
    print("=" * 40)
    
    # Create session
    constructor = create_interactive_session(domain="animals")
    
    # Add some statements
    statements = [
        "All cats are animals",
        "Some cats are black",
        "Fluffy is a cat",
        "All animals need food"
    ]
    
    for statement in statements:
        result = constructor.add_statement(statement)
        print(f"Added: {statement}")
        print(f"FOL: {result.get('fol_formula', 'N/A')}")
        print(f"Confidence: {result.get('confidence', 0.0):.2f}")
        print("-" * 30)
    
    # Analyze structure
    analysis = constructor.analyze_logical_structure()
    print("\nLogical Structure Analysis:")
    if analysis["status"] == "success":
        logical_elements = analysis["analysis"]["logical_elements"]
        print(f"Quantifiers: {logical_elements['quantifiers']}")
        print(f"Predicates: {logical_elements['predicates']}")
        print(f"Entities: {logical_elements['entities']}")
    
    # Check consistency
    consistency = constructor.validate_consistency()
    print(f"\nConsistency: {consistency.get('consistency_report', {}).get('overall_consistent', 'Unknown')}")
    
    # Get statistics
    stats = constructor.get_session_statistics()
    print(f"\nSession Statistics:")
    print(f"Total statements: {stats['metadata']['total_statements']}")
    print(f"Average confidence: {stats['metadata']['average_confidence']:.2f}")
    
    return constructor


if __name__ == "__main__":
    demo_interactive_session()

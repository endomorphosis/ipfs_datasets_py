"""Code validation example.

This example demonstrates the comprehensive validation framework
with different validation levels.
"""

from pathlib import Path
from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    ValidationLevel,
)


def main():
    """Run validation example."""
    print("=" * 60)
    print("Code Validation Example")
    print("=" * 60)
    
    # Sample code to validate
    code_to_validate = '''
"""Sample module for validation."""

from typing import List, Optional


def process_data(items: List[int]) -> List[int]:
    """Process a list of items.
    
    Args:
        items: List of integers to process
        
    Returns:
        Processed list of integers
    """
    result = []
    for item in items:
        if item > 0:
            result.append(item * 2)
    return result


class DataProcessor:
    """Process data with caching."""
    
    def __init__(self, cache_size: int = 100):
        """Initialize processor.
        
        Args:
            cache_size: Maximum cache size
        """
        self.cache_size = cache_size
        self._cache = {}
    
    def process(self, key: str, data: List[int]) -> List[int]:
        """Process data with caching.
        
        Args:
            key: Cache key
            data: Data to process
            
        Returns:
            Processed data
        """
        if key in self._cache:
            return self._cache[key]
        
        result = process_data(data)
        self._cache[key] = result
        return result
'''
    
    # Test different validation levels
    levels = [
        ValidationLevel.BASIC,
        ValidationLevel.STANDARD,
        ValidationLevel.STRICT,
        ValidationLevel.PARANOID,
    ]
    
    for level in levels:
        print(f"\n{'=' * 60}")
        print(f"Validation Level: {level.value.upper()}")
        print(f"{'=' * 60}")
        
        # Create validator
        validator = OptimizationValidator(level=level, parallel=True)
        
        # Run validation
        print("Running validation...")
        result = validator.validate_sync(
            code=code_to_validate,
            target_files=[],
            context={},
        )
        
        # Display results
        print(f"\nResult: {'✅ PASSED' if result.passed else '❌ FAILED'}")
        print(f"Execution time: {result.execution_time:.2f}s")
        
        # Show details based on level
        if result.syntax:
            print(f"\nSyntax: {'✅' if result.syntax.get('passed') else '❌'}")
            if result.syntax.get('node_count'):
                print(f"  AST nodes: {result.syntax['node_count']}")
        
        if result.types:
            print(f"Types: {'✅' if result.types.get('passed') else '❌'}")
            if not result.types.get('mypy_available'):
                print("  (mypy not available)")
        
        if result.style:
            print(f"Style: {'✅' if result.style.get('passed') else '❌'}")
            if result.style.get('score'):
                print(f"  Score: {result.style['score']:.1f}%")
        
        if result.security:
            print(f"Security: {'✅' if result.security.get('passed') else '❌'}")
            issues = result.security.get('issues_found', [])
            if issues:
                print(f"  Issues: {len(issues)}")
        
        if result.errors:
            print(f"\nErrors: {len(result.errors)}")
            for error in result.errors[:3]:
                print(f"  - {error}")
        
        if result.warnings:
            print(f"\nWarnings: {len(result.warnings)}")
            for warning in result.warnings[:3]:
                print(f"  - {warning}")
    
    print(f"\n{'=' * 60}")
    print("Validation Levels Comparison")
    print(f"{'=' * 60}")
    print("""
BASIC: Fast syntax-only validation
  - AST parsing
  - Basic syntax checks
  - Use for quick validation during development

STANDARD: Production-ready validation (recommended)
  - Syntax + Type checking
  - Unit tests
  - Balanced speed and thoroughness

STRICT: High-quality code enforcement
  - Standard + Performance checks
  - Regression detection
  - Use for critical code paths

PARANOID: Maximum validation
  - All validators enabled
  - Security scanning
  - Style enforcement
  - Use for security-sensitive code
""")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

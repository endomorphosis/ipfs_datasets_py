"""
Performance profiling for OntologyGenerator._extract_rule_based()

This script identifies the top-3 bottlenecks in rule-based entity extraction
by exercising the method with varying input sizes and complexity.
"""
import sys
import os

# Add the parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..'))

import cProfile
import pstats
import io
import time
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
)


def generate_test_data(size: str) -> str:
    """Generate test data of increasing complexity."""
    base_text = (
        "Alice Smith (Mrs. Alice) and Bob Johnson (Mr. Johnson) met at "
        "Google Inc. on January 15, 2024. They discussed a $500,000 USD agreement "
        "for medical supplies on Main Street in New York City. "
        "The plaintiff filed a claim on Section 3.2 of the contract. "
        "Patient records show diagnosis of hypertension with dosage of 50 mg daily. "
        "The API endpoint returns JSON format with REST protocol support. "
        "Asset value of 1,000,000 EUR with principal at 5% interest rate. "
    )
    
    multipliers = {
        "small": 5,
        "medium": 25,
        "large": 100,
        "xlarge": 500,
    }
    
    return base_text * multipliers.get(size, 25)


def profile_extraction(size: str = "medium"):
    """Profile OntologyGenerator._extract_rule_based() with cProfile."""
    print(f"\n{'='*80}")
    print(f"Profiling _extract_rule_based() with {size.upper()} input")
    print(f"{'='*80}\n")
    
    # Generate test data
    text = generate_test_data(size)
    print(f"Input size: {len(text)} characters ({len(text.split())} words)")
    
    # Setup generator and context
    generator = OntologyGenerator()
    config = ExtractionConfig(
        confidence_threshold=0.5,
        max_entities=200,
        max_relationships=150,
        window_size=5,
        custom_rules=[
            (r'\bArticle\s+\d+', 'ArticleReference'),
            (r'\$\d+(?:,\d{3})*(?:\.\d{2})?', 'MonetaryAmount'),
        ],
    )
    context = OntologyGenerationContext(
        domain="legal",
        data_source="test",
        data_type="text",
        config=config,
    )
    
    # Profile with cProfile
    profiler = cProfile.Profile()
    profiler.enable()
    
    start_wall = time.time()
    result = generator._extract_rule_based(text, context)
    wall_time_ms = (time.time() - start_wall) * 1000
    
    profiler.disable()
    
    # Print result summary
    print(f"\nExtraction Result:")
    print(f"  Entities: {len(result.entities)}")
    print(f"  Relationships: {len(result.relationships)}")
    print(f"  Wall-clock time: {wall_time_ms:.2f} ms")
    print(f"  Metadata: {result.metadata}")
    
    # Print top functions by cumulative time
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative")
    ps.print_stats(15)  # Top 15 functions
    
    print("\n" + s.getvalue())
    
    # Extract called functions and their times
    print("\n" + "="*80)
    print("TOP-3 BOTTLENECK ANALYSIS")
    print("="*80 + "\n")
    
    s2 = io.StringIO()
    ps2 = pstats.Stats(profiler, stream=s2).sort_stats("cumulative")
    ps2.print_stats(20)
    
    # Parse and identify top bottlenecks
    lines = s2.getvalue().split('\n')
    function_times = []
    
    for line in lines:
        if 'cumtime' in line or 'percall' in line or '---' in line:
            continue
        parts = line.split()
        if len(parts) >= 6:
            try:
                ncalls = parts[0]
                tottime = float(parts[1])
                cumtime = float(parts[2])
                func_name = ' '.join(parts[5:])
                function_times.append((cumtime, tottime, func_name, ncalls))
            except (ValueError, IndexError):
                continue
    
    # Sort by cumulative time and show top 3
    function_times.sort(reverse=True)
    
    if function_times:
        print("Top-3 functions by cumulative time:\n")
        for i, (cumtime, tottime, func_name, ncalls) in enumerate(function_times[:3], 1):
            print(f"{i}. {func_name}")
            print(f"   Cumulative time: {cumtime:.4f}s")
            print(f"   Total time: {tottime:.4f}s")
            print(f"   Call count: {ncalls}")
            print()


def benchmark_extraction_pipeline():
    """Benchmark extraction with different input sizes."""
    print("\n" + "="*80)
    print("BENCHMARK: Extraction Time vs Input Size")
    print("="*80 + "\n")
    
    generator = OntologyGenerator()
    config = ExtractionConfig(
        confidence_threshold=0.5,
        max_entities=200,
    )
    
    sizes = [("small", 5), ("medium", 25), ("large", 100), ("xlarge", 500)]
    
    print(f"{'Size':<10} {'Characters':<15} {'Words':<10} {'Time (ms)':<12} {'Entities':<10} {'Rels':<10}")
    print("-" * 70)
    
    for size_name, multiplier in sizes:
        base = (
            "Alice Smith at Google Inc. on January 15, 2024. "
            "Agreement for $500,000 USD on Main Street in New York. "
        )
        text = base * multiplier
        
        context = OntologyGenerationContext(
            domain="general",
            data_source="test",
            data_type="text",
            config=config,
        )
        
        start = time.time()
        result = generator._extract_rule_based(text, context)
        elapsed_ms = (time.time() - start) * 1000
        
        print(
            f"{size_name:<10} {len(text):<15} {len(text.split()):<10} "
            f"{elapsed_ms:<12.2f} {len(result.entities):<10} {len(result.relationships):<10}"
        )


def analyze_pattern_matching_efficiency():
    """Analyze regex pattern matching efficiency."""
    print("\n" + "="*80)
    print("ANALYSIS: Pattern Matching Efficiency")
    print("="*80 + "\n")
    
    generator = OntologyGenerator()
    context = OntologyGenerationContext(domain="legal", data_type="text")
    
    # Generate text with varying numbers of patterns
    texts = {
        "High density (many patterns)": (
            "Samuel Johnson met Elizabeth Smith at Acme Corp on 2024-01-15. "
            "They discussed USD 100,000 obligation on Fifth Avenue. "
        ) * 50,
        "Low density (few patterns)": (
            "Some text without any meaningful entities or patterns "
            "just regular english words and sentences here. "
        ) * 50,
        "Mixed density": (
            "Alice met Bob on 2024-01-15 in New York. No pattern. "
            "Jane discussed $500,000 USD. Some filler text here. "
        ) * 50,
    }
    
    print("Pattern matching efficiency (lower time = better):\n")
    for desc, text in texts.items():
        start = time.time()
        result = generator._extract_rule_based(text, context)
        elapsed_ms = (time.time() - start) * 1000
        entities_per_ms = len(result.entities) / elapsed_ms if elapsed_ms > 0 else 0
        
        print(f"{desc}")
        print(f"  Time: {elapsed_ms:.2f} ms")
        print(f"  Entities found: {len(result.entities)}")
        print(f"  Entities per ms: {entities_per_ms:.2f}")
        print()


if __name__ == "__main__":
    # Run profiling for different input sizes
    for size in ["small", "medium", "large"]:
        profile_extraction(size)
    
    # Run benchmarks
    benchmark_extraction_pipeline()
    
    # Analyze pattern matching
    analyze_pattern_matching_efficiency()
    
    print("\n" + "="*80)
    print("PROFILING COMPLETE")
    print("="*80)
    print("""
Summary of findings:
- Profile results show cumulative time spent in each function
- Top-3 bottlenecks are typically: regex finditer, set lookups, UUID generation
- Optimization opportunities:
  1. Compile regex patterns once instead of per-extraction
  2. Use dict/set for O(1) lookups instead of O(n) list operations
  3. Consider pre-allocating entity IDs or using faster ID generation
  
Run this script with different input sizes to verify scaling behavior.
""")

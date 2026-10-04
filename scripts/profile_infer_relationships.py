#!/usr/bin/env python3
"""
Profile infer_relationships() performance bottlenecks.

This script benchmarks the relationship inference code path with realistic
workloads to identify optimization opportunities. Focuses on:

1. Regex compilation overhead (verb frame patterns)
2. Entity text matching (case folding, lowercasing)
3. Co-occurrence window calculations (string searching)
4. Type inference rule lookups

Usage:
    python scripts/profile_infer_relationships.py
    python scripts/profile_infer_relationships.py --size large --visualize
"""

import argparse
import cProfile
import pstats
import io
import time
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "ipfs_datasets_py"))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
    OntologyGenerationContext,
    ExtractionConfig,
    DataType,
    ExtractionStrategy,
)


def generate_sample_entities(size: str = "medium") -> List[Entity]:
    """Generate realistic entity sets for profiling."""
    
    sizes = {
        "small": 20,
        "medium": 100,
        "large": 500,
        "xlarge": 1000,
    }
    n_entities = sizes.get(size, 100)
    
    entity_types = [
        "Person", "Organization", "Location", "Document", "Event",
        "Obligation", "Contract", "Payment", "Statute", "Case"
    ]
    
    entities = []
    for i in range(n_entities):
        entity_type = entity_types[i % len(entity_types)]
        entities.append(Entity(
            id=f"e{i:04d}",
            text=f"{entity_type} Entity {i}",
            type=entity_type,
            confidence=0.8 + (i % 20) * 0.01,  # 0.8-0.99
            properties={"index": i}
        ))
    
    return entities


def generate_sample_data(entities: List[Entity]) -> str:
    """Generate realistic text data containing entity mentions."""
    
    # Simulate legal complaint text with verb frames
    templates = [
        "{subj} owns {obj}.",
        "{subj} employs {obj} at the facility.",
        "{subj} manages {obj} during the period.",
        "{subj} obligates {obj} to pay the amount.",
        "{subj} causes {obj} to incur damages.",
        "The contract between {subj} and {obj} specifies terms.",
        "{subj} is a subsidiary of {obj}.",
        "{subj} is part of {obj}.",
        "According to the statute, {subj} must {obj}.",
        "{subj} cites {obj} in the filing.",
    ]
    
    # Create a realistic text corpus
    lines = []
    for i in range(0, len(entities) - 1, 2):
        template = templates[i % len(templates)]
        subj = entities[i].text
        obj = entities[i + 1].text
        line = template.format(subj=subj, obj=obj)
        lines.append(line)
    
    # Add some natural language filler to make it realistic
    filler = [
        "The court finds that the evidence supports this conclusion.",
        "Plaintiff alleges violations of statutory requirements.",
        "Defendant disputes the claims and requests dismissal.",
        "The parties entered into negotiations in good faith.",
        "Discovery revealed substantial documentation.",
    ]
    
    # Interleave entity mentions with filler
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if i % 3 == 0:
            result.append(filler[i % len(filler)])
    
    return " ".join(result)


def profile_infer_relationships(
    entities: List[Entity],
    data: str,
    context: OntologyGenerationContext,
    profile_enabled: bool = True,
) -> Dict[str, Any]:
    """Profile the infer_relationships method."""
    
    generator = OntologyGenerator()
    
    # Warm-up run (populates pattern caches)
    generator.infer_relationships(entities[:10], context, data[:1000])
    
    # Profiled run
    if profile_enabled:
        profiler = cProfile.Profile()
        profiler.enable()
    
    start_time = time.perf_counter()
    relationships = generator.infer_relationships(entities, context, data)
    elapsed = time.perf_counter() - start_time
    
    if profile_enabled:
        profiler.disable()
    else:
        profiler = None
    
    return {
        "elapsed_seconds": elapsed,
        "num_entities": len(entities),
        "num_relationships": len(relationships),
        "relationships_per_second": len(relationships) / elapsed if elapsed > 0 else 0,
        "profiler": profiler,
    }


def print_profile_stats(profiler: cProfile.Profile, top_n: int = 25):
    """Print top-N time-consuming function calls."""
    
    if profiler is None:
        return
    
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    
    print("\n" + "=" * 80)
    print("TOP FUNCTIONS BY CUMULATIVE TIME")
    print("=" * 80)
    ps.sort_stats(pstats.SortKey.CUMULATIVE)
    ps.print_stats(top_n)
    print(s.getvalue())
    
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    
    print("\n" + "=" * 80)
    print("TOP FUNCTIONS BY TOTAL TIME")
    print("=" * 80)
    ps.sort_stats(pstats.SortKey.TIME)
    ps.print_stats(top_n)
    print(s.getvalue())


def benchmark_sizes():
    """Benchmark across different entity set sizes."""
    
    print("\n" + "=" * 80)
    print("BENCHMARK: Relationship Inference Scaling")
    print("=" * 80)
    
    sizes = ["small", "medium", "large", "xlarge"]
    results = []
    
    for size in sizes:
        entities = generate_sample_entities(size)
        data = generate_sample_data(entities)
        config = ExtractionConfig()
        context = OntologyGenerationContext(
            data_source="profiling_sample.txt",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.HYBRID,
            config=config
        )
        
        print(f"\nBenchmarking {size} ({len(entities)} entities)...")
        result = profile_infer_relationships(
            entities, data, context, profile_enabled=False
        )
        
        print(f"  Elapsed: {result['elapsed_seconds']:.4f}s")
        print(f"  Relationships: {result['num_relationships']}")
        print(f"  Throughput: {result['relationships_per_second']:.2f} rels/sec")
        
        results.append({
            "size": size,
            "n_entities": len(entities),
            **result
        })
    
    print("\n" + "=" * 80)
    print("SCALING SUMMARY")
    print("=" * 80)
    print(f"{'Size':<10} {'Entities':>10} {'Rels':>10} {'Time (s)':>12} {'Rels/sec':>12}")
    print("-" * 80)
    for r in results:
        print(
            f"{r['size']:<10} {r['n_entities']:>10} "
            f"{r['num_relationships']:>10} {r['elapsed_seconds']:>12.4f} "
            f"{r['relationships_per_second']:>12.2f}"
        )
    
    return results


def identify_bottlenecks(profiler: cProfile.Profile) -> List[str]:
    """Analyze profiler output and identify optimization opportunities."""
    
    if profiler is None:
        return []
    
    bottlenecks = []
    
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.sort_stats(pstats.SortKey.CUMULATIVE)
    
    # Check for common bottlenecks
    stats_dict = ps.stats
    
    total_time = sum(stat[2] for stat in stats_dict.values())
    
    for func, stat in stats_dict.items():
        func_name = func[2]
        cumtime = stat[3]
        percent = (cumtime / total_time) * 100 if total_time > 0 else 0
        
        # Identify high-impact functions (>5% of total time)
        if percent > 5:
            if "finditer" in func_name or "re.compile" in func_name:
                bottlenecks.append(
                    f"⚠️  Regex overhead: {func_name} ({percent:.1f}% of time) "
                    "→ Consider pre-compiling patterns"
                )
            elif "lower" in func_name:
                bottlenecks.append(
                    f"⚠️  Case folding overhead: {func_name} ({percent:.1f}% of time) "
                    "→ Consider caching lowercased strings"
                )
            elif "find" in func_name or "index" in func_name:
                bottlenecks.append(
                    f"⚠️  String search overhead: {func_name} ({percent:.1f}% of time) "
                    "→ Consider position caching or indexing"
                )
            elif "_get_verb_patterns" in func_name or "_get_type_inference" in func_name:
                bottlenecks.append(
                    f"⚠️  Pattern lookup overhead: {func_name} ({percent:.1f}% of time) "
                    "→ Verify lazy loading is working correctly"
                )
    
    return bottlenecks


def main():
    parser = argparse.ArgumentParser(
        description="Profile infer_relationships() performance"
    )
    parser.add_argument(
        "--size",
        choices=["small", "medium", "large", "xlarge"],
        default="medium",
        help="Entity set size for profiling"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run benchmark across all sizes"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="Number of top functions to show in profile"
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate visualization (requires gprof2dot, graphviz)"
    )
    
    args = parser.parse_args()
    
    if args.benchmark:
        benchmark_sizes()
        return
    
    # Single profiling run
    print(f"\n🔍 Profiling infer_relationships() with {args.size} entity set...")
    
    entities = generate_sample_entities(args.size)
    data = generate_sample_data(entities)
    config = ExtractionConfig()
    context = OntologyGenerationContext(
        data_source="profiling_sample.txt",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.HYBRID,
        config=config
    )
    
    result = profile_infer_relationships(entities, data, context, profile_enabled=True)
    
    print("\n" + "=" * 80)
    print("PROFILING RESULTS")
    print("=" * 80)
    print(f"Entities:             {result['num_entities']}")
    print(f"Relationships found:  {result['num_relationships']}")
    print(f"Elapsed time:         {result['elapsed_seconds']:.4f} seconds")
    print(f"Throughput:           {result['relationships_per_second']:.2f} rels/sec")
    
    print_profile_stats(result["profiler"], top_n=args.top_n)
    
    # Identify optimization opportunities
    bottlenecks = identify_bottlenecks(result["profiler"])
    if bottlenecks:
        print("\n" + "=" * 80)
        print("OPTIMIZATION OPPORTUNITIES")
        print("=" * 80)
        for b in bottlenecks:
            print(f"\n{b}")
    else:
        print("\n✅ No major bottlenecks detected (all functions < 5% of total time)")
    
    # Visualization
    if args.visualize:
        print("\n📊 Generating call graph visualization...")
        try:
            import subprocess
            
            # Save profile data
            profile_file = "/tmp/infer_relationships.prof"
            result["profiler"].dump_stats(profile_file)
            
            # Generate DOT file
            dot_file = "/tmp/infer_relationships.dot"
            subprocess.run([
                "gprof2dot",
                "-f", "pstats",
                profile_file,
                "-o", dot_file
            ], check=True)
            
            # Generate PNG
            png_file = "/tmp/infer_relationships.png"
            subprocess.run([
                "dot",
                "-Tpng",
                dot_file,
                "-o", png_file
            ], check=True)
            
            print(f"✅ Visualization saved to: {png_file}")
            print(f"   Open with: xdg-open {png_file}")
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Visualization failed: {e}")
            print("   Install dependencies: pip install gprof2dot && sudo apt install graphviz")
        except FileNotFoundError:
            print("❌ gprof2dot or graphviz not found")
            print("   Install: pip install gprof2dot && sudo apt install graphviz")


if __name__ == "__main__":
    main()

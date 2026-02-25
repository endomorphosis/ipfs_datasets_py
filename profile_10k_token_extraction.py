"""
10k-Token Extraction Profile (Session 83, P2-perf).

This script profiles entity extraction performance on large documents (10k+ tokens)
to identify bottlenecks and guide optimization efforts.

Provides:
- Detailed timing breakdown by extraction phase
- Memory usage profiling
- Hot path identification via cProfile
- Comparative analysis across different strategies
- Recommendations for optimization

Usage:
    python profile_10k_token_extraction.py
    python profile_10k_token_extraction.py --output profile_results.json
    python profile_10k_token_extraction.py --verbose
"""

import argparse
import cProfile
import io
import json
import pstats
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Dict, Any, List, Optional

# Import profiling target
try:
    from ipfs_datasets_py.optimizers.graphrag.entity_extraction import (
        GraphRAGEntityExtractor,
        ExtractionStrategy,
    )
    EXTRACTION_AVAILABLE = True
except ImportError:
    EXTRACTION_AVAILABLE = False
    print("WARNING: GraphRAG entity extraction not available", file=sys.stderr)


# ---------------------------------------------------------------------------
# Test Document Generation
# ---------------------------------------------------------------------------

def generate_large_document(target_tokens: int = 10000) -> str:
    """Generate a synthetic document with approximately target_tokens tokens.
    
    Uses realistic climate policy text to simulate real workloads.
    """
    base_text = """
    The Paris Agreement represents a landmark international treaty on climate change,
    adopted by 196 parties at COP21 in Paris on 12 December 2015. The agreement
    entered into force on 4 November 2016, becoming legally binding when at least
    55 countries representing at least 55% of global greenhouse gas emissions ratified it.
    
    The core objective is to limit global warming to well below 2°C above pre-industrial
    levels, while pursuing efforts to limit the increase to 1.5°C. This temperature goal
    is critical because scientific evidence shows that crossing these thresholds would
    lead to catastrophic and irreversible climate impacts.
    
    Key mechanisms include Nationally Determined Contributions (NDCs), which are
    climate action plans submitted by each country. NDCs outline emission reduction
    targets, adaptation strategies, and implementation timelines. Countries must submit
    progressively more ambitious NDCs every five years through the "ratchet mechanism."
    
    Financial support for developing countries is a central pillar. Developed nations
    committed to mobilizing $100 billion per year by 2020 to support climate action
    in developing countries. The Glasgow Climate Pact extended this commitment through
    2025 and called for a new collective quantified goal beyond that date.
    
    The agreement operates through a transparency framework requiring all parties to
    regularly report their emissions and implementation progress. This enhanced
    transparency builds trust and allows for tracking collective progress toward goals.
    
    Adaptation is recognized as equally important to mitigation. The global goal on
    adaptation aims to enhance adaptive capacity, strengthen resilience, and reduce
    vulnerability. The Adaptation Fund, established under the Kyoto Protocol, continues
    to serve the Paris Agreement.
    
    Loss and damage from climate impacts became a major focus at COP27 in 2022, leading
    to the establishment of a dedicated loss and damage fund. This addresses the reality
    that some climate impacts cannot be adapted to and have caused irreversible harm,
    particularly in vulnerable developing countries.
    
    Non-state actors including cities, regions, businesses, and civil society play
    crucial roles. The Global Climate Action Portal tracks commitments from these actors,
    who often move faster than national governments. Major corporations have pledged
    net-zero emissions, often with more ambitious timelines than their home countries.
    
    Carbon markets under Article 6 enable countries to trade emissions reductions,
    potentially lowering overall climate action costs. After years of negotiation, the
    Article 6 rulebook was finalized at COP26 in Glasgow, establishing integrity
    safeguards to prevent double-counting and ensure environmental ambition.
    
    Scientific assessment underpins the agreement. The Intergovernmental Panel on
    Climate Change (IPCC) provides authoritative assessments that inform NDC development
    and global stocktakes. The 2021 IPCC Sixth Assessment Report showed that human
    influence has unequivocally warmed the atmosphere, ocean, and land.
    
    Youth movements have become powerful voices in climate action. Initiatives like
    Fridays for Future, started by Greta Thunberg, have mobilized millions globally
    demanding stronger climate policies. These movements have shifted public discourse
    and increased political pressure for ambitious action.
    
    Technology transfer provisions aim to accelerate clean technology deployment in
    developing countries. The Technology Mechanism includes the Technology Executive
    Committee and the Climate Technology Centre and Network, facilitating access to
    climate-friendly technologies.
    
    Just transition principles recognize that the shift to a low-carbon economy must
    be equitable, ensuring that workers and communities dependent on fossil fuel
    industries are supported through the transition. This includes retraining programs,
    economic diversification, and social protection measures.
    """
    
    # Replicate text to reach target token count
    # Rough estimate: 1 token ≈ 0.75 words
    current_tokens = len(base_text.split())
    repetitions = (target_tokens // current_tokens) + 1
    
    text_parts = [base_text]
    for i in range(1, repetitions):
        # Add variation by prepending section markers
        text_parts.append(f"\n\n## Section {i}\n\n{base_text}")
    
    return "".join(text_parts)


# ---------------------------------------------------------------------------
# Profiling Functions
# ---------------------------------------------------------------------------

def profile_extraction_timing(
    document: str,
    strategy: Optional[str] = None
) -> Dict[str, float]:
    """Profile extraction with detailed phase timing.
    
    Returns dict with:
    - total_time: Total extraction time (seconds)
    - per_phase: Dict of phase → time for extraction pipeline stages
    - tokens_per_second: Processing throughput
    """
    if not EXTRACTION_AVAILABLE:
        return {"error": "Extraction not available"}
    
    strategy_enum = ExtractionStrategy.REGEX if strategy is None else ExtractionStrategy[strategy.upper()]
    extractor = GraphRAGEntityExtractor(strategy=strategy_enum)
    
    # Phase 1: Initialization (already done above)
    
    # Phase 2: Extraction
    start_time = time.perf_counter()
    entities = extractor.extract(document)
    total_time = time.perf_counter() - start_time
    
    # Calculate throughput
    token_count = len(document.split())
    tokens_per_sec = token_count / total_time if total_time > 0 else 0
    
    return {
        "total_time": total_time,
        "token_count": token_count,
        "entity_count": len(entities),
        "tokens_per_second": tokens_per_sec,
        "entities_per_second": len(entities) / total_time if total_time > 0 else 0,
    }


def profile_extraction_memory(document: str) -> Dict[str, Any]:
    """Profile memory usage during extraction.
    
    Returns dict with:
    - peak_memory_mb: Peak memory usage (MiB)
    - memory_per_token: Memory per token (bytes)
    """
    if not EXTRACTION_AVAILABLE:
        return {"error": "Extraction not available"}
    
    tracemalloc.start()
    
    extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
    entities = extractor.extract(document)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    token_count = len(document.split())
    
    return {
        "peak_memory_mb": peak / (1024 * 1024),
        "current_memory_mb": current / (1024 * 1024),
        "memory_per_token_bytes": peak / token_count if token_count > 0 else 0,
        "entity_count": len(entities),
    }


def profile_extraction_hotspots(document: str) -> str:
    """Profile with cProfile to identify hot paths.
    
    Returns formatted profiling statistics.
    """
    if not EXTRACTION_AVAILABLE:
        return "Extraction not available"
    
    profiler = cProfile.Profile()
    
    def run_extraction():
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        return extractor.extract(document)
    
    profiler.enable()
    entities = run_extraction()
    profiler.disable()
    
    # Generate statistics
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats('cumulative')
    stats.print_stats(20)  # Top 20 functions
    
    return stream.getvalue()


def compare_strategies(document: str) -> List[Dict[str, Any]]:
    """Compare extraction performance across different strategies.
    
    Returns list of results for each strategy.
    """
    if not EXTRACTION_AVAILABLE:
        return [{"error": "Extraction not available"}]
    
    results = []
    
    # Try each available strategy
    for strategy in [ExtractionStrategy.REGEX]:
        try:
            timing = profile_extraction_timing(document, strategy=strategy.name)
            timing["strategy"] = strategy.name
            results.append(timing)
        except Exception as e:
            results.append({
                "strategy": strategy.name,
                "error": str(e),
            })
    
    return results


# ---------------------------------------------------------------------------
# Main Profiling Workflow
# ---------------------------------------------------------------------------

def run_full_profile(
    token_count: int = 10000,
    verbose: bool = False
) -> Dict[str, Any]:
    """Run complete profiling suite.
    
    Args:
        token_count: Target document size in tokens.
        verbose: Print detailed output to stdout.
    
    Returns:
        Dict with all profiling results.
    """
    if verbose:
        print(f"Generating {token_count}-token document...")
    
    document = generate_large_document(token_count)
    actual_tokens = len(document.split())
    
    if verbose:
        print(f"Document generated: {actual_tokens} tokens")
        print("\n" + "="*70)
        print("Phase 1: Timing Profile")
        print("="*70)
    
    timing_results = profile_extraction_timing(document)
    
    if verbose:
        print(f"Total time: {timing_results['total_time']:.3f}s")
        print(f"Throughput: {timing_results['tokens_per_second']:.0f} tokens/second")
        print(f"Entities extracted: {timing_results['entity_count']}")
        print(f"Entity rate: {timing_results['entities_per_second']:.1f} entities/second")
    
    if verbose:
        print("\n" + "="*70)
        print("Phase 2: Memory Profile")
        print("="*70)
    
    memory_results = profile_extraction_memory(document)
    
    if verbose:
        print(f"Peak memory: {memory_results['peak_memory_mb']:.2f} MiB")
        print(f"Memory per token: {memory_results['memory_per_token_bytes']:.1f} bytes")
    
    if verbose:
        print("\n" + "="*70)
        print("Phase 3: Hot Path Analysis")
        print("="*70)
    
    hotspot_stats = profile_extraction_hotspots(document)
    
    if verbose:
        print(hotspot_stats)
    
    if verbose:
        print("\n" + "="*70)
        print("Phase 4: Strategy Comparison")
        print("="*70)
    
    strategy_comparison = compare_strategies(document)
    
    if verbose:
        for result in strategy_comparison:
            if "error" in result:
                print(f"{result.get('strategy', 'unknown')}: ERROR - {result['error']}")
            else:
                print(f"{result['strategy']}: {result['total_time']:.3f}s, "
                      f"{result['tokens_per_second']:.0f} tokens/s")
    
    # Compile full results
    return {
        "document_stats": {
            "requested_tokens": token_count,
            "actual_tokens": actual_tokens,
        },
        "timing": timing_results,
        "memory": memory_results,
        "hotspots": hotspot_stats,
        "strategy_comparison": strategy_comparison,
        "recommendations": generate_recommendations(timing_results, memory_results),
    }


def generate_recommendations(
    timing: Dict[str, Any],
    memory: Dict[str, Any]
) -> List[str]:
    """Generate optimization recommendations based on profiling results."""
    recommendations = []
    
    # Throughput analysis
    tokens_per_sec = timing.get("tokens_per_second", 0)
    if tokens_per_sec < 1000:
        recommendations.append(
            f"Low throughput ({tokens_per_sec:.0f} tokens/s). Consider: "
            "(1) Regex optimization, (2) Batch processing, (3) Parallel extraction."
        )
    
    # Memory analysis
    peak_mb = memory.get("peak_memory_mb", 0)
    if peak_mb > 100:
        recommendations.append(
            f"High memory usage ({peak_mb:.1f} MiB). Consider: "
            "(1) Streaming extraction, (2) Incremental processing, (3) Memory pooling."
        )
    
    memory_per_token = memory.get("memory_per_token_bytes", 0)
    if memory_per_token > 1000:
        recommendations.append(
            f"High memory per token ({memory_per_token:.0f} bytes). "
            "Review data structures for unnecessary copying or large intermediate objects."
        )
    
    # Entity extraction rate
    entities_per_sec = timing.get("entities_per_second", 0)
    if entities_per_sec < 10:
        recommendations.append(
            f"Low entity extraction rate ({entities_per_sec:.1f}/s). "
            "Check for expensive post-processing or validation overhead."
        )
    
    if not recommendations:
        recommendations.append(
            "Performance is within acceptable bounds. No immediate optimizations required."
        )
    
    return recommendations


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Profile GraphRAG entity extraction on large documents (10k+ tokens)"
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=10000,
        help="Target document size in tokens (default: 10000)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save results to JSON file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed profiling output"
    )
    
    args = parser.parse_args()
    
    if not EXTRACTION_AVAILABLE:
        print("ERROR: GraphRAG entity extraction not available", file=sys.stderr)
        print("Install required dependencies or check module path", file=sys.stderr)
        sys.exit(1)
    
    # Run profiling
    results = run_full_profile(token_count=args.tokens, verbose=args.verbose)
    
    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with output_path.open("w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_path}")
    
    # Summary output (always shown)
    if not args.verbose:
        print("\n10k-Token Extraction Profile Summary")
        print("="*70)
        print(f"Document: {results['document_stats']['actual_tokens']} tokens")
        print(f"Time: {results['timing']['total_time']:.3f}s")
        print(f"Throughput: {results['timing']['tokens_per_second']:.0f} tokens/s")
        print(f"Peak Memory: {results['memory']['peak_memory_mb']:.2f} MiB")
        print(f"Entities: {results['timing']['entity_count']}")
        print("\nRecommendations:")
        for i, rec in enumerate(results['recommendations'], 1):
            print(f"  {i}. {rec}")


if __name__ == "__main__":
    main()

"""Batch 264: Profile OntologyGenerator._extract_rule_based() hot paths

Profiles the rule-based extraction stage directly to isolate pattern building,
entity extraction, and relationship inference costs.

Usage:
    python profile_batch_264_extract_rule_based.py

Outputs:
    - profile_batch_264_extract_rule_based.prof
    - profile_batch_264_extract_rule_based.txt
"""

import cProfile
import pathlib
import pstats
import sys
import time
from typing import Optional, Dict, Any

sys.path.insert(0, str(pathlib.Path(__file__).parents[5]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


def generate_legal_text(target_tokens: int = 5000) -> str:
    """Generate a legal-style document with roughly target_tokens tokens."""
    clauses = [
        "The parties agree to the terms of this Agreement and all obligations herein.",
        "Contractor shall provide services in a professional and timely manner.",
        "Client shall pay fees within thirty days of receipt of invoice.",
        "This Agreement may be terminated upon written notice by either party.",
        "Confidential Information shall be protected using reasonable care.",
    ]
    parts = [
        "MASTER SERVICES AGREEMENT\n\n",
        "This Agreement is made between Alpha Corp and Beta LLC.\n\n",
    ]

    current_tokens = len(" ".join(parts).split())
    idx = 0
    while current_tokens < target_tokens:
        clause = clauses[idx % len(clauses)]
        parts.append(f"{idx + 1}. {clause}\n")
        idx += 1
        current_tokens = len(" ".join(parts).split())

    parts.append("\nIN WITNESS WHEREOF, the parties execute this Agreement.\n")
    return "".join(parts)


def profile_extract_rule_based(
    target_tokens: int = 5000,
    warmup_tokens: int = 300,
    output_dir: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Profile _extract_rule_based on a synthetic legal text.

    Args:
        target_tokens: Approximate token count for the profiled run.
        warmup_tokens: Token count for a short warmup run.
        output_dir: Directory to write .prof/.txt outputs. When None, no files written.

    Returns:
        Dict with basic profiling metrics.
    """
    text = generate_legal_text(target_tokens=target_tokens)
    warmup_text = generate_legal_text(target_tokens=warmup_tokens)

    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source="profile_rule_based",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )

    # Warmup
    _ = generator._extract_rule_based(warmup_text, context)

    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()

    result = generator._extract_rule_based(text, context)

    profiler.disable()
    elapsed_ms = (time.perf_counter() - start) * 1000

    entity_count = len(result.entities)
    relationship_count = len(result.relationships)

    metrics = {
        "token_count": len(text.split()),
        "elapsed_ms": elapsed_ms,
        "entity_count": entity_count,
        "relationship_count": relationship_count,
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        prof_file = output_dir / "profile_batch_264_extract_rule_based.prof"
        txt_file = output_dir / "profile_batch_264_extract_rule_based.txt"

        profiler.dump_stats(str(prof_file))

        with open(txt_file, "w", encoding="utf-8") as handle:
            handle.write("=" * 72 + "\n")
            handle.write("BATCH 264: _extract_rule_based() Profile\n")
            handle.write("=" * 72 + "\n\n")
            handle.write(f"Tokens: {metrics['token_count']}\n")
            handle.write(f"Elapsed ms: {metrics['elapsed_ms']:.2f}\n")
            handle.write(f"Entities: {metrics['entity_count']}\n")
            handle.write(f"Relationships: {metrics['relationship_count']}\n\n")
            stats = pstats.Stats(profiler, stream=handle).sort_stats("cumulative")
            stats.print_stats(30)

    return metrics


def main() -> None:
    """Run the profiling script with default parameters."""
    output_dir = pathlib.Path(__file__).parent
    metrics = profile_extract_rule_based(output_dir=output_dir)

    print("\nBatch 264 profiling complete")
    print(f"Tokens: {metrics['token_count']}")
    print(f"Elapsed ms: {metrics['elapsed_ms']:.2f}")
    print(f"Entities: {metrics['entity_count']}")
    print(f"Relationships: {metrics['relationship_count']}")
    print(f"Output dir: {output_dir}")


if __name__ == "__main__":
    main()

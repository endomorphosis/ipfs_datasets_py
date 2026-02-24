"""Batch 269: Profile consistency cycle detection on large ontologies.

Profiles ontology_critic_consistency.evaluate_consistency() with synthetic
ontologies to identify DFS/cycle-detection hotspots.

Usage:
    python profile_batch_269_consistency_cycles.py

Outputs:
    - profile_batch_269_consistency_cycles.prof
    - profile_batch_269_consistency_cycles.txt
"""

import cProfile
import pathlib
import pstats
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import (
    evaluate_consistency,
)


def build_ontology(
    entity_count: int,
    relationship_count: int,
    *,
    with_cycle: bool = False,
) -> Dict[str, Any]:
    """Create a synthetic ontology with optional hierarchy cycles."""
    if entity_count <= 0:
        raise ValueError("entity_count must be > 0")
    if relationship_count < 0:
        raise ValueError("relationship_count must be >= 0")

    entities: List[Dict[str, Any]] = []
    for idx in range(entity_count):
        entities.append(
            {
                "id": f"E{idx}",
                "text": f"Entity {idx}",
                "type": "Concept",
            }
        )

    relationships: List[Dict[str, Any]] = []
    for idx in range(relationship_count):
        src = f"E{idx % entity_count}"
        tgt = f"E{(idx + 1) % entity_count}"
        rel_type = "is_a" if idx % 3 == 0 else "part_of"
        relationships.append(
            {
                "id": f"R{idx}",
                "source_id": src,
                "target_id": tgt,
                "type": rel_type,
            }
        )

    if with_cycle and entity_count >= 3:
        relationships.append(
            {"id": "cycle_1", "source_id": "E0", "target_id": "E1", "type": "is_a"}
        )
        relationships.append(
            {"id": "cycle_2", "source_id": "E1", "target_id": "E2", "type": "is_a"}
        )
        relationships.append(
            {"id": "cycle_3", "source_id": "E2", "target_id": "E0", "type": "is_a"}
        )

    return {
        "entities": entities,
        "relationships": relationships,
    }


def profile_consistency(
    entity_count: int = 800,
    relationship_count: int = 1200,
    with_cycle: bool = True,
    output_dir: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Profile evaluate_consistency on synthetic ontology.

    Args:
        entity_count: Number of entities in synthetic ontology.
        relationship_count: Number of relationships in synthetic ontology.
        with_cycle: Whether to insert a cycle for DFS detection.
        output_dir: Directory to write .prof/.txt outputs.

    Returns:
        Dict with profiling metrics.
    """
    ontology = build_ontology(
        entity_count,
        relationship_count,
        with_cycle=with_cycle,
    )

    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()

    score = evaluate_consistency(ontology, context=None)

    profiler.disable()
    elapsed_ms = (time.perf_counter() - start) * 1000

    metrics = {
        "entity_count": entity_count,
        "relationship_count": relationship_count,
        "with_cycle": with_cycle,
        "elapsed_ms": elapsed_ms,
        "score": score,
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        prof_file = output_dir / "profile_batch_269_consistency_cycles.prof"
        txt_file = output_dir / "profile_batch_269_consistency_cycles.txt"

        profiler.dump_stats(str(prof_file))

        with open(txt_file, "w", encoding="utf-8") as handle:
            handle.write("=" * 72 + "\n")
            handle.write("BATCH 269: Consistency Cycle Profiling\n")
            handle.write("=" * 72 + "\n\n")
            handle.write(f"Entities: {metrics['entity_count']}\n")
            handle.write(f"Relationships: {metrics['relationship_count']}\n")
            handle.write(f"With cycle: {metrics['with_cycle']}\n")
            handle.write(f"Elapsed ms: {metrics['elapsed_ms']:.2f}\n")
            handle.write(f"Score: {metrics['score']:.4f}\n\n")
            stats = pstats.Stats(profiler, stream=handle).sort_stats("cumulative")
            stats.print_stats(40)

    return metrics


def main() -> None:
    """Run the profiling script with default parameters."""
    output_dir = pathlib.Path(__file__).parent
    metrics = profile_consistency(output_dir=output_dir)

    print("\nBatch 269 profiling complete")
    print(f"Entities: {metrics['entity_count']}")
    print(f"Relationships: {metrics['relationship_count']}")
    print(f"With cycle: {metrics['with_cycle']}")
    print(f"Elapsed ms: {metrics['elapsed_ms']:.2f}")
    print(f"Score: {metrics['score']:.4f}")
    print(f"Output dir: {output_dir}")


if __name__ == "__main__":
    main()

"""Batch 267: Profile prover round-trips via ProverIntegrationAdapter.

Profiles verification overhead for a batch of logical statements using a
stub prover to avoid external dependencies. This isolates adapter cost and
caching/aggregation overhead.

Usage:
    python profile_batch_267_prover_roundtrips.py

Outputs:
    - profile_batch_267_prover_roundtrips.prof
    - profile_batch_267_prover_roundtrips.txt
"""

import cProfile
import pathlib
import pstats
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).parents[5]))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    ProverIntegrationAdapter,
)


class StubProver:
    """Lightweight prover stub for profiling adapter round-trips."""

    def __init__(self, delay_ms: float = 0.0):
        self.delay_ms = delay_ms

    def prove(self, formula: str, timeout: Optional[float] = None) -> bool:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        # Simple deterministic computation to avoid no-op optimization.
        _ = sum(ord(ch) for ch in formula) % 2
        return True


def build_statements(count: int) -> List[str]:
    """Build a list of deterministic logical statements."""
    base = [
        "forall x (P(x) -> Q(x))",
        "exists y (R(y) & S(y))",
        "forall x forall y (R(x,y) -> S(y))",
        "exists x (P(x) & ~Q(x))",
        "forall x (P(x) <-> Q(x))",
    ]
    statements: List[str] = []
    for idx in range(count):
        stmt = base[idx % len(base)] + f" # {idx}"
        statements.append(stmt)
    return statements


def profile_prover_roundtrips(
    statement_count: int = 60,
    delay_ms: float = 0.0,
    output_dir: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Profile ProverIntegrationAdapter.verify_statement round-trips.

    Args:
        statement_count: Number of statements to verify.
        delay_ms: Optional delay per prover call to emulate real solver time.
        output_dir: Directory for .prof/.txt outputs.

    Returns:
        Dict with profiling metrics.
    """
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    adapter.provers = {"stub": StubProver(delay_ms=delay_ms)}

    statements = build_statements(statement_count)

    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()

    valid_count = 0
    for statement in statements:
        result = adapter.verify_statement(statement)
        if result.overall_valid:
            valid_count += 1

    profiler.disable()
    elapsed_ms = (time.perf_counter() - start) * 1000

    metrics = {
        "statement_count": statement_count,
        "elapsed_ms": elapsed_ms,
        "avg_ms": elapsed_ms / max(1, statement_count),
        "valid_count": valid_count,
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        prof_file = output_dir / "profile_batch_267_prover_roundtrips.prof"
        txt_file = output_dir / "profile_batch_267_prover_roundtrips.txt"

        profiler.dump_stats(str(prof_file))

        with open(txt_file, "w", encoding="utf-8") as handle:
            handle.write("=" * 72 + "\n")
            handle.write("BATCH 267: Prover Round-Trip Profile\n")
            handle.write("=" * 72 + "\n\n")
            handle.write(f"Statements: {metrics['statement_count']}\n")
            handle.write(f"Elapsed ms: {metrics['elapsed_ms']:.2f}\n")
            handle.write(f"Avg ms/statement: {metrics['avg_ms']:.2f}\n")
            handle.write(f"Valid count: {metrics['valid_count']}\n\n")
            stats = pstats.Stats(profiler, stream=handle).sort_stats("cumulative")
            stats.print_stats(40)

    return metrics


def main() -> None:
    """Run the profiling script with default parameters."""
    output_dir = pathlib.Path(__file__).parent
    metrics = profile_prover_roundtrips(output_dir=output_dir)

    print("\nBatch 267 profiling complete")
    print(f"Statements: {metrics['statement_count']}")
    print(f"Elapsed ms: {metrics['elapsed_ms']:.2f}")
    print(f"Avg ms/statement: {metrics['avg_ms']:.2f}")
    print(f"Valid count: {metrics['valid_count']}")
    print(f"Output dir: {output_dir}")


if __name__ == "__main__":
    main()

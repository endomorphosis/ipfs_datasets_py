"""A failed native task must remain in the retained benchmark trial."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


def _exercise_failure():
    benchmarks = Path(__file__).resolve().parents[4] / "benchmarks"
    sys.path.insert(0, str(benchmarks))
    spec = importlib.util.spec_from_file_location("isabelle_benchmark_failure_test", benchmarks / "bench_shared_prover_isabelle.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    scheduler = SimpleNamespace(active_leases=lambda: [])
    retained = {"receipts": [{"task_id": "isabelle-0", "status": "cancelled", "result": None}]}
    receipt = SimpleNamespace(successful_task_ids=(), to_dict=lambda: retained, receipts=(
        SimpleNamespace(task_id="isabelle-0", result=None, cache_bypassed_execution=False),))
    plan = SimpleNamespace(budget=SimpleNamespace(cpu_slots=3, memory_bytes=2304 * 1024**2,
        process_slots=12, max_portfolio_width=1), proof_safety_enabled=True,
        to_dict=lambda: {"planned_max_workers": 1})
    with patch.object(benchmark, "get_global_resource_scheduler", return_value=scheduler), \
         patch.object(benchmark, "build_tasks", return_value=[SimpleNamespace(task_id="isabelle-0")]), \
         patch.object(benchmark, "execute_datasets_native_bundle", return_value=SimpleNamespace(receipt=receipt, plan=plan)):
        row = benchmark.trial(1, 1)
    assert row["correctness_passed"] is False
    assert row["receipt"] == retained
    assert row["native_checks"] == {"smt": 0, "lean": 0, "tlc": 0, "isabelle": 0}
    assert row["checks"]["isabelle_generated_theorem_accepted"] is False
    assert row["checks"]["dependency_order"] is False
    assert row["execution_seconds"] >= 0


def test_failed_isabelle_without_payload_preserves_trial_receipt_and_counts():
    # The CLI selects sibling package roots before import. Reproduce that fresh
    # process boundary even when another test loaded the nested legacy package.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve())],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    _exercise_failure()

"""Real subprocess qualification for default admission and external backoff."""
import importlib.util
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler

_path = Path(__file__).resolve().parents[4] / "benchmarks/bench_resource_aware_proving.py"
_spec = importlib.util.spec_from_file_location("resource_proving_benchmark", _path)
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)
SOLVERS = [name for name in ("z3", "cvc5") if shutil.which(name)]
pytestmark = pytest.mark.skipif(not SOLVERS, reason="requires a real installed SMT solver")


def test_default_profile_runs_real_parallel_portfolios_and_releases_resources(tmp_path, monkeypatch):
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", str(tmp_path / "scheduler.json"))
    scheduler = get_global_resource_scheduler()
    assert scheduler.config.proof_safety_enabled
    trial = benchmark.run_trial(scheduler, SOLVERS, workers=2, jobs=4)
    assert trial["solver_checks"] == 4 * len(SOLVERS)
    assert trial["leases_remaining"] == 0
    assert trial["peak_reserved_cpu_slots"] <= scheduler.config.total_cpu_slots
    assert trial["peak_reserved_memory_mb"] <= scheduler.config.total_memory_mb
    assert {item["expected"] for item in trial["results"]} == {"sat", "unsat"}


@pytest.mark.parametrize("pressure", ["cpu", "memory", "io"])
def test_real_solver_waits_for_external_pressure_cooldown_then_recovers(tmp_path, pressure):
    result = benchmark.run_pressure_probe(tmp_path / "scheduler.json", SOLVERS[0], pressure)
    assert result["launches_during_pressure"] == 0
    assert result["recovery_after_clear_seconds"] >= result["cooldown_seconds"] - 0.1
    assert result["verdict"] == "sat"
    assert result["leases_remaining"] == 0

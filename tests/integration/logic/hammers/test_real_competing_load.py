"""Opt-in bounded real competing-load regression tests.

IPFS_DATASETS_RUN_PROVING_STRESS=1 enables CPU and memory stress workers.
The benchmark enforces minimum live memory headroom and bounded workers.
"""
import importlib.util
import os
from pathlib import Path
import shutil

import pytest

_spec = importlib.util.spec_from_file_location('real_proving_stress', Path(__file__).resolve().parents[4] / 'benchmarks/bench_proving_real_stress.py')
stress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stress)
SOLVERS = [name for name in ('z3', 'cvc5') if shutil.which(name)]
pytestmark = pytest.mark.skipif(os.environ.get('IPFS_DATASETS_RUN_PROVING_STRESS') != '1'
    or not SOLVERS or not Path('/proc/self/schedstat').is_file(),
    reason='opt-in Linux real stress: IPFS_DATASETS_RUN_PROVING_STRESS=1 with SMT solver')


@pytest.mark.parametrize('kind', ['cpu', 'memory'])
def test_real_competitor_causes_backoff_and_recovery(tmp_path, kind):
    result = stress.run_real_pressure(tmp_path/'scheduler.json', SOLVERS[0], kind)
    assert result['launches_during_pressure']==0 and result['leases_remaining']==0
    assert result['cooldown_observed_seconds'] >= 1.99
    if kind=='memory': assert result['peak_external_rss_mb'] >= 768
    else: assert result['peak_cpu_wait_percent'] > 50


def test_parallel_portfolios_complete_under_real_external_load(tmp_path):
    result = stress.run_competing_batch(tmp_path/'scheduler.json', SOLVERS, jobs=16)
    assert result['solver_checks']==16*len(SOLVERS)
    assert result['leases_remaining']==0 and result['peak_reserved_cpu_slots'] <= 4

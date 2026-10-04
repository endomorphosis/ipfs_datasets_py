"""Small CLI/transport/source-scope checks; no archive installation or native tools."""
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def bench_module():
    path = Path(__file__).resolve().parents[4] / "benchmarks/bench_isabelle_shared_installation.py"
    spec = importlib.util.spec_from_file_location("isabelle_shared_installation_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "3601", "invalid"])
def test_cli_rejects_unbounded_or_invalid_timeout_before_work(bench_module, value):
    with pytest.raises(SystemExit) as exc:
        bench_module.parser().parse_args(["--archive", "input.tar.gz", "--output", "fresh", "--timeout", value])
    assert exc.value.code == 2


def test_cli_default_is_finite_and_requires_explicit_archive_output(bench_module):
    args = bench_module.parser().parse_args(["--archive", "input.tar.gz", "--output", "fresh"])
    assert args.timeout == 900 and args.archive == Path("input.tar.gz")
    with pytest.raises(SystemExit):
        bench_module.parser().parse_args([])


def test_mirror_changes_only_transport_and_restores_selector_after_failure(bench_module):
    legacy = bench_module.installer.legacy
    original = legacy.select_strict_pin
    pin = original("isabelle", platform_key=legacy.detect_platform_key())
    url = "http://127.0.0.1:12345/official.tar.gz"
    with pytest.raises(RuntimeError, match="controlled failure"):
        with bench_module.mirrored_pin(pin, url):
            observed = legacy.select_strict_pin("isabelle", platform_key=pin.platform)
            assert observed == replace(pin, artifact_url=url)
            assert observed.sha256 == pin.sha256 and observed.version == pin.version
            with pytest.raises(ValueError, match="different pin"):
                legacy.select_strict_pin("isabelle", platform_key="wrong-platform")
            raise RuntimeError("controlled failure")
    assert legacy.select_strict_pin is original


def test_source_scope_contains_production_controller_worker_and_native_resource_chain(bench_module):
    sources = bench_module.source_hashes()
    paths = {Path(path) for path in sources}
    expected = {
        "logic/backends/installers/isabelle_installation.py",
        "logic/backends/installers/isabelle_install_worker.py",
        "logic/backends/installers/isabelle_profile.py",
        "logic/backends/installers/isabelle_preparation.py",
        "logic/backends/process.py",
        "optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "optimizers/logic_theorem_optimizer/proof_resource_safety.py",
    }
    assert all(bench_module.DATASETS / "ipfs_datasets_py" / name in paths for name in expected)
    assert Path(bench_module.__file__).resolve() in paths
    assert all(len(value) == 64 for value in sources.values())
    assert not any(path.name == "bench_isabelle_installation_bounds.py" for path in paths)


def test_retained_digest_limits_actual_bytes(bench_module, tmp_path):
    path = tmp_path / "artifact"
    path.write_bytes(b"bounded")
    assert len(bench_module.digest(path, max_bytes=7)) == 64
    with pytest.raises(Exception, match="cap|bound|limit|large"):
        bench_module.digest(path, max_bytes=6)


def test_wait_delta_uses_actual_shared_scheduler_summary_shape(bench_module, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False,
    ))
    before = owner.snapshot()
    with owner.acquire("validation", cpu_slots=1, memory_mb=128, child_process_slots=1, timeout=0):
        pass
    after = owner.snapshot()
    assert isinstance(after["wait_time_seconds"], dict)
    assert after["wait_time_seconds"]["count"] == before["wait_time_seconds"]["count"] + 1
    delta = bench_module.shared_wait_total_delta(before, after)
    assert type(delta) is float and delta >= 0
    assert delta == after["wait_time_seconds"]["total"] - before["wait_time_seconds"]["total"]
    assert owner.active_leases() == []

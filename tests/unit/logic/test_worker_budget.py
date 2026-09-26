"""Worker budget tracks CPUs and free memory."""
from ipfs_datasets_py.logic.autoformal.worker_budget import worker_budget


def test_idle_machine_uses_every_cpu() -> None:
    assert worker_budget(cpu_count=20, load_average=0.2, available_mb=32_000) == 20


def test_high_load_and_low_memory_scale_down() -> None:
    assert worker_budget(cpu_count=20, load_average=16.0, available_mb=32_000) == 5
    assert worker_budget(cpu_count=20, load_average=0.0, available_mb=700) == 1

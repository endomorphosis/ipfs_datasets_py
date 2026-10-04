"""Worker budget tracks CPUs and free memory."""
from ipfs_datasets_py.logic.autoformal.worker_budget import resolve_worker_count, worker_budget


def test_idle_machine_uses_every_cpu() -> None:
    assert worker_budget(cpu_count=20, load_average=0.2, available_mb=32_000) == 20


def test_existing_load_does_not_shrink_a_full_cpu_width() -> None:
    assert worker_budget(cpu_count=20, load_average=16.0, available_mb=32_000) == 20
    assert worker_budget(cpu_count=20, load_average=16.0, available_mb=32_000, kind="autoencoder") == 20


def test_low_memory_scales_down() -> None:
    assert worker_budget(cpu_count=20, available_mb=700, kind="compiler") == 2
    assert worker_budget(cpu_count=20, available_mb=700, kind="autoencoder") == 1


def test_zero_request_uses_the_machine_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.autoformal.worker_budget.worker_budget",
        lambda **_kwargs: 6,
    )
    assert resolve_worker_count(0, maximum=32) == 6
    assert resolve_worker_count(None, maximum=32) == 6
    assert resolve_worker_count(3, maximum=32) == 3
    assert resolve_worker_count(40, maximum=32) == 32


def test_compiler_target_pool_follows_the_machine_when_unset(monkeypatch) -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        _legal_ir_parallel_worker_count,
    )

    monkeypatch.delenv("IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", raising=False)
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.autoformal.worker_budget.worker_budget",
        lambda **_kwargs: 6,
    )
    assert _legal_ir_parallel_worker_count(requested=None, item_count=10) == 6
    assert _legal_ir_parallel_worker_count(requested=None, item_count=1) == 1
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", "2")
    assert _legal_ir_parallel_worker_count(requested=None, item_count=10) == 2

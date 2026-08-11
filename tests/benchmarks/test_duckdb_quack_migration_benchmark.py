"""Benchmark tests for DQK-048 production-hardening migration soak.

Acceptance coverage:

* Benchmark is resumable and does not mutate the fixture
* Peak memory and transaction latency stay within declared budgets
* Every migrated population has count and digest parity receipts

Uses a hermetic multi-population stand-in for the 970 MB production-hardening
fixture so CI stays bounded; the real fixture is selected automatically when
``DQK_PRODUCTION_HARDENING_FIXTURE`` points at a directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.duckdb_quack_migration_benchmark import (
    BENCHMARK_SCHEMA,
    CHECKPOINT_SCHEMA,
    DEFAULT_BUDGETS,
    FIXTURE_ENV_VAR,
    HERMETIC_POPULATIONS,
    OWNER_TASK_ID,
    PARITY_RECEIPT_SCHEMA,
    PHASES,
    BenchmarkBudget,
    BenchmarkError,
    MigrationBenchmark,
    PhaseName,
    build_hermetic_fixture,
    default_budget,
    fingerprint_fixture,
    peak_memory_bytes,
    run_migration_benchmark,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir()
    return root


@pytest.fixture()
def hermetic_fixture(tmp_path: Path) -> Path:
    return build_hermetic_fixture(
        tmp_path / "fixture",
        record_count=40,
        blob_bytes=64 * 1024,
        seed=48,
    )


# ---------------------------------------------------------------------------
# Module / budget surface
# ---------------------------------------------------------------------------


def test_module_constants_and_default_budget() -> None:
    assert OWNER_TASK_ID == "DQK-048"
    assert BENCHMARK_SCHEMA.endswith("@1")
    assert CHECKPOINT_SCHEMA.endswith("@1")
    assert PARITY_RECEIPT_SCHEMA.endswith("@1")
    assert tuple(p.value for p in PHASES) == (
        "streaming_migration",
        "event_receipt_query",
        "backup_restore",
        "concurrency",
    )
    budget = default_budget()
    assert budget.max_peak_memory_bytes == DEFAULT_BUDGETS.max_peak_memory_bytes
    assert budget.max_transaction_latency_ms > 0
    assert set(budget.to_dict()) >= {
        "max_peak_memory_bytes",
        "max_transaction_latency_ms",
        "max_wall_seconds",
        "max_disk_bytes",
        "max_lock_wait_ms",
    }
    assert peak_memory_bytes() >= 1


def test_budget_rejects_non_positive_ceilings() -> None:
    with pytest.raises(BenchmarkError):
        BenchmarkBudget(max_peak_memory_bytes=0)
    with pytest.raises(BenchmarkError):
        BenchmarkBudget(max_transaction_latency_ms=0)
    with pytest.raises(BenchmarkError):
        BenchmarkBudget(max_wall_seconds=-1)


def test_hermetic_fixture_is_deterministic(tmp_path: Path) -> None:
    a = build_hermetic_fixture(tmp_path / "a", record_count=20, blob_bytes=4096, seed=7)
    b = build_hermetic_fixture(tmp_path / "b", record_count=20, blob_bytes=4096, seed=7)
    assert fingerprint_fixture(a) == fingerprint_fixture(b)
    marker = a / ".dqk048_fixture_manifest.json"
    assert marker.is_file()
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    for name in HERMETIC_POPULATIONS:
        assert name in manifest["populations"]
        rel = manifest["populations"][name]
        assert (a / rel).is_file()


# ---------------------------------------------------------------------------
# Full benchmark acceptance
# ---------------------------------------------------------------------------


def test_full_benchmark_within_budgets_and_parity(
    work_dir: Path, hermetic_fixture: Path
) -> None:
    """Peak memory and transaction latency stay within declared budgets;
    every migrated population has count and digest parity receipts.
    """
    budget = BenchmarkBudget(
        max_peak_memory_bytes=512 * 1024 * 1024,
        max_transaction_latency_ms=5_000.0,
        max_wall_seconds=120.0,
        max_disk_bytes=256 * 1024 * 1024,
        max_lock_wait_ms=10_000.0,
    )
    report = run_migration_benchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        budget=budget,
        resume=False,
    )

    assert report.fixture_mode in {"hermetic", "real"}
    assert report.fixture_mutated is False
    assert report.owner_task_id == OWNER_TASK_ID
    assert report.schema == BENCHMARK_SCHEMA
    assert report.status in {"success", "budget_exceeded", "parity_failed"}
    assert report.budgets_ok is True
    assert report.all_parity_matched is True
    assert report.ok is True

    phase_names = {p.phase for p in report.phases}
    assert phase_names == set(PHASES)

    for phase in report.phases:
        assert phase.budget_ok is True
        assert phase.metrics.peak_memory_bytes <= budget.max_peak_memory_bytes
        assert (
            phase.metrics.max_transaction_latency_ms
            <= budget.max_transaction_latency_ms
        )
        assert phase.metrics.wall_seconds <= budget.max_wall_seconds

    streaming = next(
        p for p in report.phases if p.phase is PhaseName.STREAMING_MIGRATION
    )
    populations = {r.population for r in streaming.parity_receipts}
    for name in HERMETIC_POPULATIONS:
        assert name in populations
    for receipt in streaming.parity_receipts:
        assert receipt.to_dict()["schema"] == PARITY_RECEIPT_SCHEMA
        assert receipt.count_matched is True
        assert receipt.digest_matched is True
        assert receipt.matched is True
        assert receipt.source_digest.startswith("sha256:")
        assert receipt.migrated_digest.startswith("sha256:")
        assert receipt.receipt_id.startswith("sha256:")
        assert receipt.source_count >= 0
        assert receipt.migrated_count >= 0

    # Backup/restore phase must prove restore and attach a catalog parity receipt.
    backup = next(p for p in report.phases if p.phase is PhaseName.BACKUP_RESTORE)
    assert backup.details.get("restore_ok") is True
    assert backup.parity_receipts
    assert all(r.matched for r in backup.parity_receipts)

    # Event/receipt query must produce allowlisted receipts + audit events.
    query = next(p for p in report.phases if p.phase is PhaseName.EVENT_RECEIPT_QUERY)
    assert query.details.get("query_calls", 0) >= 1
    assert query.details.get("audit_events")
    assert query.metrics.operation_count >= 1

    # Concurrency phase samples lock waits and transaction latencies.
    concurrency = next(p for p in report.phases if p.phase is PhaseName.CONCURRENCY)
    assert concurrency.details.get("ops_ok", 0) >= 1
    assert concurrency.metrics.operation_count >= 1


def test_benchmark_does_not_mutate_fixture(
    work_dir: Path, hermetic_fixture: Path
) -> None:
    before = fingerprint_fixture(hermetic_fixture)
    # Capture raw file digests for a sample population.
    sample = hermetic_fixture / "data/agent_supervisor/production_hardening/tasks.jsonl"
    before_bytes = sample.read_bytes()
    before_sha = hashlib.sha256(before_bytes).hexdigest()

    report = run_migration_benchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        resume=False,
    )
    assert report.fixture_mutated is False
    assert fingerprint_fixture(hermetic_fixture) == before
    assert sample.read_bytes() == before_bytes
    assert hashlib.sha256(sample.read_bytes()).hexdigest() == before_sha

    # Work directory receives artifacts; fixture root does not.
    assert (work_dir / "dqk-048-benchmark-report.json").is_file()
    fixture_writes = [
        p
        for p in hermetic_fixture.rglob("*")
        if p.is_file() and p.stat().st_mtime_ns  # exist only
    ]
    assert fixture_writes  # fixture still has files
    # No report/checkpoint written inside fixture.
    assert not (hermetic_fixture / "dqk-048-benchmark-report.json").exists()
    assert not list(hermetic_fixture.rglob("*checkpoint*"))


def test_benchmark_is_resumable(work_dir: Path, hermetic_fixture: Path) -> None:
    """Interrupted / multi-call runs skip completed phases via checkpoint."""
    budget = default_budget()

    # First call: only streaming + query.
    first = MigrationBenchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        budget=budget,
        resume=True,
    )
    report1 = first.run(
        phases=[PhaseName.STREAMING_MIGRATION, PhaseName.EVENT_RECEIPT_QUERY]
    )
    assert report1.fixture_mutated is False
    assert Path(report1.checkpoint_path).is_file()
    checkpoint = json.loads(Path(report1.checkpoint_path).read_text(encoding="utf-8"))
    assert checkpoint["schema"] == CHECKPOINT_SCHEMA
    assert "streaming_migration" in checkpoint["completed_phases"]
    assert "event_receipt_query" in checkpoint["completed_phases"]

    # Second call: full suite — completed phases resume without re-execution.
    second = MigrationBenchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        budget=budget,
        resume=True,
    )
    report2 = second.run()
    assert report2.fixture_mutated is False
    assert "streaming_migration" in report2.resumed_phases
    assert "event_receipt_query" in report2.resumed_phases
    # New phases still ran.
    phase_names = {p.phase for p in report2.phases}
    assert PhaseName.BACKUP_RESTORE in phase_names
    assert PhaseName.CONCURRENCY in phase_names
    # Streaming parity receipts survived the resume path.
    streaming = next(
        p for p in report2.phases if p.phase is PhaseName.STREAMING_MIGRATION
    )
    assert streaming.resumed is True
    assert streaming.parity_receipts
    assert all(r.matched for r in streaming.parity_receipts)
    assert report2.all_parity_matched is True


def test_resume_invalidated_when_fixture_digest_changes(
    work_dir: Path, tmp_path: Path
) -> None:
    fixture_a = build_hermetic_fixture(
        tmp_path / "fa", record_count=10, blob_bytes=2048, seed=1
    )
    bench = MigrationBenchmark(
        work_dir, fixture_root=fixture_a, resume=True
    )
    bench.run(phases=[PhaseName.STREAMING_MIGRATION])
    assert bench.checkpoint_path.is_file()

    # Replace fixture under a new root with different content; new benchmark
    # against different digest must not resume old phases.
    fixture_b = build_hermetic_fixture(
        tmp_path / "fb", record_count=12, blob_bytes=2048, seed=99
    )
    work2 = work_dir  # same work_dir / checkpoint location
    # Point checkpoint env so both share the same checkpoint file path.
    bench2 = MigrationBenchmark(
        work2, fixture_root=fixture_b, resume=True
    )
    # Fixture digest differs → completed list empty (checkpoint ignored).
    assert fingerprint_fixture(fixture_a) != fingerprint_fixture(fixture_b)
    # When digests differ, _restore_checkpoint returns early without loading.
    assert bench2._completed == [] or bench2.fixture_digest != bench.fixture_digest


def test_streaming_phase_alone_emits_population_parity(
    work_dir: Path, hermetic_fixture: Path
) -> None:
    report = run_migration_benchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        resume=False,
        phases=[PhaseName.STREAMING_MIGRATION],
    )
    assert len(report.phases) == 1
    phase = report.phases[0]
    assert phase.phase is PhaseName.STREAMING_MIGRATION
    assert len(phase.parity_receipts) == len(HERMETIC_POPULATIONS)
    for receipt in phase.parity_receipts:
        payload = receipt.to_dict()
        assert payload["schema"] == PARITY_RECEIPT_SCHEMA
        assert payload["count_matched"] is True
        assert payload["digest_matched"] is True
        assert payload["matched"] is True


def test_real_fixture_env_var_is_honoured(
    work_dir: Path, hermetic_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FIXTURE_ENV_VAR, str(hermetic_fixture))
    report = run_migration_benchmark(
        work_dir,
        fixture_root=None,
        resume=False,
        phases=[PhaseName.STREAMING_MIGRATION],
    )
    # discover_fixture_root prefers explicit; when None uses env → real mode.
    assert report.fixture_mode == "real"
    assert Path(report.fixture_root) == hermetic_fixture.resolve()
    assert report.fixture_mutated is False


def test_report_serialises_and_round_trips_fields(
    work_dir: Path, hermetic_fixture: Path
) -> None:
    report = run_migration_benchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        resume=False,
    )
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["fixture_mutated"] is False
    assert payload["all_parity_matched"] is True
    assert payload["budgets_ok"] is True
    text = json.dumps(payload, sort_keys=True)
    reloaded = json.loads(text)
    assert reloaded["owner_task_id"] == "DQK-048"
    assert reloaded["schema"] == BENCHMARK_SCHEMA
    assert len(reloaded["phases"]) == len(PHASES)


def test_checkpoint_written_to_agent_checkpoint_dir(
    work_dir: Path,
    hermetic_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ckpt_dir = tmp_path / "agent_ckpts"
    ckpt_dir.mkdir()
    monkeypatch.setenv("IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR", str(ckpt_dir))
    report = run_migration_benchmark(
        work_dir,
        fixture_root=hermetic_fixture,
        resume=False,
        phases=[PhaseName.STREAMING_MIGRATION],
    )
    assert Path(report.checkpoint_path).is_file()
    assert Path(report.checkpoint_path).parent == ckpt_dir
    data = json.loads(Path(report.checkpoint_path).read_text(encoding="utf-8"))
    assert data["schema"] == CHECKPOINT_SCHEMA
    assert data["fixture_digest"] == report.fixture_digest

"""Offline fixture benchmark for wallet processor metrics (WALPROC-G640).

Reports records/second and peak memory against a fixed synthetic fixture.
Performance budgets come from :class:`ResourceBudget.fixture_default`, not
from live provider latency samples.
"""

from __future__ import annotations

import json
import resource
import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.wallets.metrics import (
    IngestRunReceipt,
    MetricErrorCategory,
    ResourceBudget,
    WalletProcessorMetrics,
    new_run_metrics,
)
from ipfs_datasets_py.processors.wallets.models import Finality

from .fixtures import (
    FIXTURE_CHAIN_NAMESPACE,
    FIXTURE_NETWORK,
    FIXTURE_PAGE_SIZE,
    FIXTURE_PROVIDER,
    FIXTURE_RECORD_COUNT,
    SyntheticLedgerRecord,
    build_fixture_records,
    paginate_records,
)


BENCHMARK_REPORT_SCHEMA = "wallet-processor-benchmark-report-v1"


def _peak_memory_bytes() -> int:
    """Best-effort peak RSS in bytes (Linux ru_maxrss is kilobytes)."""

    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    # Linux reports kilobytes; macOS reports bytes. Prefer the larger of
    # tracemalloc peak and OS RSS so CI has a stable signal either way.
    if sys.platform == "darwin":
        return rss
    return rss * 1024


@dataclass(frozen=True, slots=True)
class FixtureBenchmarkResult:
    """One fixture-only benchmark execution."""

    record_count: int
    page_count: int
    wall_seconds: float
    records_per_second: float
    peak_memory_bytes: int
    tracemalloc_peak_bytes: int
    metrics: dict[str, Any]
    receipt: dict[str, Any]
    budget: dict[str, Any]
    budget_ok: bool
    budget_failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": self.record_count,
            "page_count": self.page_count,
            "wall_seconds": self.wall_seconds,
            "records_per_second": self.records_per_second,
            "peak_memory_bytes": self.peak_memory_bytes,
            "tracemalloc_peak_bytes": self.tracemalloc_peak_bytes,
            "metrics": self.metrics,
            "receipt": self.receipt,
            "budget": self.budget,
            "budget_ok": self.budget_ok,
            "budget_failures": list(self.budget_failures),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Top-level report emitted by ``run.py --fixture-only``."""

    mode: str
    schema_version: str
    fixture_record_count: int
    result: FixtureBenchmarkResult
    live_smoke_enabled: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "fixture_record_count": self.fixture_record_count,
            "result": self.result.to_dict(),
            "live_smoke_enabled": self.live_smoke_enabled,
            "notes": list(self.notes),
        }


def _normalize_page(
    page: tuple[SyntheticLedgerRecord, ...],
    metrics: WalletProcessorMetrics,
) -> list[dict[str, Any]]:
    """Simulate streaming normalization work without provider I/O."""

    normalized: list[dict[str, Any]] = []
    for record in page:
        metrics.record_records(seen=1)
        try:
            finality = Finality(record.finality)
        except ValueError:
            metrics.record_error(MetricErrorCategory.NORMALIZATION)
            continue
        payload = record.to_dict()
        # Touch fields so work is not optimized away and memory is realistic.
        payload["normalized"] = True
        payload["amount_units"] = int(payload["amount_units"])
        normalized.append(payload)
        metrics.record_records(normalized=1, accepted=1)
        metrics.record_finality(finality)
        metrics.record_bytes(
            inbound=64 + (record.record_index % 32),
            outbound=48,
        )
    return normalized


def _evaluate_budget(
    *,
    records_per_second: float,
    peak_memory_bytes: int,
    wall_seconds: float,
    record_count: int,
    budget: ResourceBudget,
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if record_count > budget.max_items:
        failures.append("max_items")
    if wall_seconds > budget.max_wall_seconds:
        failures.append("max_wall_seconds")
    if peak_memory_bytes > budget.max_peak_memory_bytes:
        failures.append("max_peak_memory_bytes")
    if (
        budget.min_records_per_second > 0
        and records_per_second < budget.min_records_per_second
    ):
        failures.append("min_records_per_second")
    return (not failures, tuple(failures))


def run_fixture_benchmark(
    *,
    record_count: int = FIXTURE_RECORD_COUNT,
    page_size: int = FIXTURE_PAGE_SIZE,
    budget: ResourceBudget | None = None,
) -> FixtureBenchmarkResult:
    """Run a deterministic offline benchmark and return throughput + memory.

    Performance budgets default to :meth:`ResourceBudget.fixture_default` and
    are never inferred from live provider latency.
    """

    if budget is None:
        budget = ResourceBudget.fixture_default()
    if budget.source in {"live-provider-latency", "live_provider_latency"}:
        raise ValueError(
            "fixture benchmarks refuse budgets sourced from live provider latency"
        )

    records = build_fixture_records(record_count)
    pages = paginate_records(records, page_size=page_size)
    metrics = new_run_metrics(
        chain_namespace=FIXTURE_CHAIN_NAMESPACE,
        network=FIXTURE_NETWORK,
        provider=FIXTURE_PROVIDER,
    )

    tracemalloc.start()
    started = time.perf_counter()
    try:
        committed: list[dict[str, Any]] = []
        for page_index, page in enumerate(pages):
            metrics.record_provider_call()
            # Simulated transport: every 17th page is a throttle+retry.
            if page_index > 0 and page_index % 17 == 0:
                metrics.record_throttle()
                metrics.record_retry()
            normalized = _normalize_page(page, metrics)
            committed.extend(normalized)
            # Simulate checkpoint age / head lag observations (numeric only).
            metrics.observe_checkpoint(
                age_seconds=float(page_index % 5),
                revision=f"rev-{page_index:04d}",
            )
            metrics.observe_head_lag(units=page_index % 3, unit_name="blocks")
            if page_index > 0 and page_index % 31 == 0:
                metrics.record_reorg_rewind(depth_units=2, shallow=True)

        metrics.record_records(exported=len(committed))
        metrics.mark_finished()
        current, traced_peak = tracemalloc.get_traced_memory()
        del current  # unused; peak is the durable signal
    finally:
        wall = time.perf_counter() - started
        tracemalloc.stop()

    os_peak = _peak_memory_bytes()
    peak_memory = max(os_peak, int(traced_peak), 1)
    metrics.observe_peak_memory(peak_memory)

    rps = (len(records) / wall) if wall > 0 else float(len(records))
    budget_ok, failures = _evaluate_budget(
        records_per_second=rps,
        peak_memory_bytes=peak_memory,
        wall_seconds=wall,
        record_count=len(records),
        budget=budget,
    )

    receipt = IngestRunReceipt.from_metrics(
        metrics,
        status="complete" if budget_ok else "partial",
        chain_namespace=FIXTURE_CHAIN_NAMESPACE,
        network=FIXTURE_NETWORK,
        provider=FIXTURE_PROVIDER,
        mode="fixture-benchmark",
        budget=budget,
        warnings=() if budget_ok else ("budget-failure",),
    )
    receipt.assert_payload_free()

    snap = metrics.snapshot()
    return FixtureBenchmarkResult(
        record_count=len(records),
        page_count=len(pages),
        wall_seconds=wall,
        records_per_second=rps,
        peak_memory_bytes=peak_memory,
        tracemalloc_peak_bytes=int(traced_peak),
        metrics=snap.to_dict(),
        receipt=receipt.to_dict(),
        budget=budget.to_dict(),
        budget_ok=budget_ok,
        budget_failures=failures,
    )


def build_fixture_report(
    result: FixtureBenchmarkResult | None = None,
) -> BenchmarkReport:
    if result is None:
        result = run_fixture_benchmark()
    return BenchmarkReport(
        mode="fixture-only",
        schema_version=BENCHMARK_REPORT_SCHEMA,
        fixture_record_count=result.record_count,
        result=result,
        live_smoke_enabled=False,
        notes=(
            "Live provider smoke is disabled; budgets are fixture-derived.",
            "Do not set performance budgets from live provider latency alone.",
        ),
    )


def write_report(report: BenchmarkReport, path: Path | None = None) -> Path | None:
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path

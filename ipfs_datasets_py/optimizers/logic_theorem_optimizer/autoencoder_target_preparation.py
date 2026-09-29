"""Prepare complete immutable bridge targets without consulting metric caches.

This is an explicit offline artifact builder, not an admission or publication
path. Workers independently verify its content/configuration binding. The
conservative source manifest hashes package Python contents rather than mtimes;
it intentionally invalidates targets after even unrelated package-code edits.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import deque
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import threading
import time
from typing import Any, Callable, Iterator, Sequence


_PROCESS_CONTEXT: dict[str, Any] | None = None


def target_snapshot_config(training_config: Any):
    """Bind actual local producer contents and relevant runtime configuration."""
    global _PROCESS_CONTEXT
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    from .legal_ir_target_snapshot import TargetSnapshotConfig
    from . import modal_autoencoder

    require_workspace_logic_tree()
    package_root = Path(__file__).resolve().parents[2]
    sources = {}
    for path in sorted(package_root.rglob("*.py")):
        if path.is_symlink() or package_root not in path.resolve().parents:
            raise ValueError(f"target producer source cannot alias another tree: {path}")
        if path.is_dir():
            # Some checked-in fixture directories intentionally end in .py.
            continue
        sources[path.relative_to(package_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    distributions = sorted({
        (str(dist.metadata.get("Name", "")), str(dist.version))
        for dist in importlib.metadata.distributions()
    })
    context = {
        "sources": sources,
        "dependencies": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "distributions_sha256": hashlib.sha256(json.dumps(distributions, separators=(",", ":")).encode()).hexdigest(),
            "distribution_identity_scope": "installed names/versions; external dependency bytes not attested",
            "adapter_workers": os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", ""),
            "target_timeout_seconds": modal_autoencoder._legal_ir_target_timeout_seconds(),
            "producer": "direct-multiview-no-metric-cache-v1",
            "source_identity_scope": "package Python contents checked before/after operation; preloaded bytecode before first check is not attested",
        },
    }
    if _PROCESS_CONTEXT is not None and context != _PROCESS_CONTEXT:
        raise ValueError("target producer code/runtime changed in resident process; start a fresh process")
    _PROCESS_CONTEXT = context
    return TargetSnapshotConfig(
        bridge_names=tuple(training_config.legal_ir_bridge_names),
        evaluate_provers=training_config.legal_ir_evaluate_provers,
        parallel_workers=training_config.legal_ir_parallel_workers,
        code_sha256=sources,
        dependency_provenance={
            **context["dependencies"],
            "target_timeout_enforcement": (
                "main_thread_sigalrm" if training_config.legal_ir_parallel_workers == 1
                and modal_autoencoder._legal_ir_target_timeout_enabled(
                    modal_autoencoder._legal_ir_target_timeout_seconds()
                ) else "none_in_parallel_target_threads_or_without_signal_support"
            ),
        },
        target_timeout_seconds=modal_autoencoder._legal_ir_target_timeout_seconds(),
    )


def unique_training_samples(samples: Sequence[Any], validation: Sequence[Any]) -> list[Any]:
    """Union split members without allowing an ID to alias different content."""
    members: dict[str, Any] = {}
    for sample in (*samples, *validation):
        prior = members.get(sample.sample_id)
        if prior is not None and prior.to_json() != sample.to_json():
            raise ValueError("sample ID aliases different sample content across splits")
        members.setdefault(sample.sample_id, sample)
    return list(members.values())


def _bounded_target_results(generate: Callable[[Any], Any], samples: Sequence[Any],
                            workers: int) -> Iterator[tuple[Any, Any]]:
    """Retain at most ``workers`` generated targets while preserving sample order.

    ``Executor.map`` may eagerly finish the entire corpus while the artifact
    writer compresses its first record. Submission here advances only when the
    writer has consumed a result, keeping that queue bounded.
    """
    if workers == 1:
        for sample in samples:
            yield sample, generate(sample)
        return
    remaining = iter(samples)
    with ThreadPoolExecutor(max_workers=min(len(samples), workers)) as executor:
        pending = deque()
        for _ in range(min(len(samples), workers)):
            sample = next(remaining)
            pending.append((sample, executor.submit(generate, sample)))
        while pending:
            sample, future = pending.popleft()
            yield sample, future.result()
            del future
            sample = next(remaining, None)
            if sample is not None:
                pending.append((sample, executor.submit(generate, sample)))


def _bridge_report_telemetry(report: Any = None, *, outer_timeout: Exception | None = None) -> dict[str, Any]:
    """Preserve observations outside target bytes, without inferring missing reports.

    Multiview may catch an adapter exception, including a target timeout, and
    return a partial report. Its failure strings are retained exactly; they are
    not reconstructed from loss names or interpreted as typed exceptions here.
    """
    if report is None:
        names = {kind: None for kind in ("attempted", "implemented", "failed", "accepted")}
    else:
        names = {
            "attempted": list(report.bridge_names),
            "implemented": sorted(report.reports),
            "failed": sorted(report.failures),
            "accepted": sorted(name for name, item in report.reports.items() if item.accepted),
        }
    return {
        "report_received": report is not None,
        "report_accepted": report.accepted if report is not None else None,
        **{f"{kind}_bridge_count": len(value) if value is not None else None for kind, value in names.items()},
        **{f"{kind}_bridge_names": value for kind, value in names.items()},
        "failures": dict(sorted(report.failures.items())) if report is not None else {},
        "outer_timeout": ({"exception_type": type(outer_timeout).__name__, "message": str(outer_timeout)}
                          if outer_timeout is not None else None),
    }


def prepare_training_targets(records: Sequence[Any], path: str | Path, *,
                             training_config: Any = None,
                             validation_records: Sequence[Any] = (),
                             artifact_format: str = "json") -> dict[str, Any]:
    """Build a sealed target snapshot for SampleRecord inputs, never model weights.

    Writes one new artifact, exclusively. There is no owner registration, Lake
    admission, network publication or metric-cache lookup. Timeout fallback
    targets remain explicitly retryable observations in the snapshot status.
    ``artifact_format="bundle"`` streams individual compressed target shards;
    the default JSON representation preserves the existing artifact behavior.
    """
    from .autoencoder_training_worker import (
        SampleRecord, TrainingConfig, _JOB_LOCK, _worker_environment,
    )
    from .legal_samples import build_us_code_sample
    from .legal_ir_target_snapshot import build_target_snapshot
    from . import modal_autoencoder as modal
    from ...logic.bridge import evaluate_legal_ir_multiview

    config = training_config or TrainingConfig()
    if not isinstance(artifact_format, str) or artifact_format not in {"json", "bundle"}:
        raise ValueError("artifact_format must be json or bundle")
    if not isinstance(config, TrainingConfig):
        raise TypeError("training_config must be TrainingConfig")
    all_records = (*records, *validation_records)
    if not records or any(not isinstance(row, SampleRecord) for row in all_records):
        raise ValueError("target preparation requires nonempty SampleRecord inputs")
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("target preparation must start on the main thread")
    if not _JOB_LOCK.acquire(blocking=False):
        raise ValueError("target preparation cannot run beside another job in this process")
    started = time.perf_counter()
    try:
        with _worker_environment():
            bound_config = target_snapshot_config(config)
            sample_started = time.perf_counter()
            split_samples = {
                "training": [build_us_code_sample(**asdict(row)) for row in records],
                "validation": [build_us_code_sample(**asdict(row)) for row in validation_records],
            }
            samples = unique_training_samples(split_samples["training"], split_samples["validation"])
            sample_seconds = time.perf_counter() - sample_started

            def generate(sample):
                try:
                    report = modal._evaluate_legal_ir_multiview_with_timeout(
                        evaluate_legal_ir_multiview,
                        timeout_seconds=bound_config.target_timeout_seconds,
                        text=sample.text, bridge_names=config.legal_ir_bridge_names,
                        document_id=sample.sample_id, evaluate_provers=False,
                        citation=sample.citation, source=sample.source,
                        source_embedding=sample.embedding_vector,
                        cache=False,
                    )
                    return sample.sample_id, report.training_target(), "ready", _bridge_report_telemetry(report)
                except modal._LegalIRTargetTimeout as exc:
                    cache_key = modal._legal_ir_target_cache_key(
                        sample, bridge_names=config.legal_ir_bridge_names, evaluate_provers=False,
                    )
                    target = modal._legal_ir_timeout_training_target(
                        sample, bridge_names=config.legal_ir_bridge_names,
                        cache_key=cache_key, timeout_seconds=bound_config.target_timeout_seconds,
                    )
                    return sample.sample_id, target, "timeout", _bridge_report_telemetry(outer_timeout=exc)

            generation_intervals = []
            generation_lock = threading.Lock()
            statuses = {}
            bridge_report_telemetry = {}

            def timed_generate(sample):
                generate_started = time.perf_counter()
                try:
                    return generate(sample)
                finally:
                    interval = (generate_started, time.perf_counter())
                    with generation_lock:
                        generation_intervals.append(interval)

            def target_records():
                generated = _bounded_target_results(timed_generate, samples, config.legal_ir_parallel_workers)
                try:
                    for sample, (key, target, status, telemetry) in generated:
                        statuses[key] = status
                        bridge_report_telemetry[key] = telemetry
                        yield sample, target, status
                        # Do not retain the prior target while producing the next.
                        del target
                    if target_snapshot_config(config) != bound_config:
                        raise ValueError("target producer changed while building snapshot")
                finally:
                    generated.close()

            artifact_started = time.perf_counter()
            if artifact_format == "bundle":
                from .legal_ir_target_bundle import write_target_bundle
                generated_records = target_records()
                try:
                    saved = write_target_bundle(path, generated_records, config=bound_config)
                finally:
                    generated_records.close()
                snapshot_id = saved["snapshot_id"]
            else:
                rows = list(target_records())
                snapshot = build_target_snapshot(
                    samples, {sample.sample_id: target for sample, target, _ in rows},
                    config=bound_config, statuses=statuses,
                )
                saved = snapshot.save(path)
                snapshot_id = snapshot.snapshot_id
            artifact_seconds = time.perf_counter() - artifact_started
            # Union, rather than sum, keeps this a wall-time measure when
            # parallel producers overlap. Time waiting for the writer is out.
            target_seconds = 0.0
            prior_end = 0.0
            for interval_start, interval_end in sorted(generation_intervals):
                target_seconds += max(0.0, interval_end - max(prior_end, interval_start))
                prior_end = max(prior_end, interval_end)
            artifact = {key: saved[key] for key in ("path", "sha256", "bytes")}
            return {
                "schema_version": "autoencoder-target-preparation-v1",
                "target_snapshot_id": snapshot_id,
                "artifact": artifact, "sample_count": len(samples),
                "legal_ir_target_count": len(statuses),
                "statuses": statuses,
                "split_target_status_counts": {
                    split: {status: sum(statuses[sample.sample_id] == status for sample in members)
                            for status in sorted({statuses[sample.sample_id] for sample in members})}
                    for split, members in split_samples.items()
                },
                "timeout_fallback_count": sum(status == "timeout" for status in statuses.values()),
                "returned_report_count": sum(item["report_received"] for item in bridge_report_telemetry.values()),
                "bridge_failure_sample_count": sum(bool(item["failures"]) for item in bridge_report_telemetry.values()),
                "status_definitions": {
                    "ready": "a returned multiview report produced a target; does not imply bridge acceptance or admission",
                    "timeout": "the outer target timeout escaped evaluation; a fallback target was produced",
                },
                "bridge_report_telemetry": bridge_report_telemetry,
                "artifact_format": artifact_format,
                "model_independent_targets": True,
                "training_executed": False,
                "preparation_scope": "training and repeated tuning targets only; no independent canary is selected by this producer",
                "artifact_statistics": saved.get("statistics", {}),
                "maximum_pending_generation_results": min(len(samples), config.legal_ir_parallel_workers),
                "artifact_builder_retains_all_targets": artifact_format == "json",
                "bridge_names": list(config.legal_ir_bridge_names),
                "legal_ir_evaluate_provers": False,
                "legal_ir_parallel_workers": config.legal_ir_parallel_workers,
                "metric_disk_cache": 0, "metric_process_cache_used": False,
                "multiview_process_cache_used": False,
                "target_timeout_enforcement": bound_config.dependency_provenance["target_timeout_enforcement"],
                "cache_observation": "targets built directly; metric and multiview caches bypassed; OS cache uncontrolled",
                "sample_preparation_seconds": sample_seconds,
                "target_generation_seconds": target_seconds,
                "target_generation_seconds_per_span": target_seconds / len(samples),
                "target_generation_timing_scope": "union of producer call wall intervals; parallel generation may overlap bundle encoding",
                "target_generate_call_seconds": sum(end - start for start, end in generation_intervals),
                "target_generation_and_artifact_seconds": artifact_seconds,
                "target_pipeline_non_generation_seconds": max(0.0, artifact_seconds - target_seconds),
                "elapsed_seconds": time.perf_counter() - started,
                "admitted": False,
            }
    finally:
        _JOB_LOCK.release()


__all__ = ["prepare_training_targets", "target_snapshot_config", "unique_training_samples"]

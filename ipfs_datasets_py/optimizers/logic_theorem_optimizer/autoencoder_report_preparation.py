"""Build bounded full native bridge reports for a verified daemon handoff.

Reports are generated once with default guidance, without metric or multiview
cache reuse. The report codec preserves their native graph sharing and derives
the optimizer target identity; this builder never writes a second target bundle.
Source-record authority and corpus membership remain the caller's responsibility.
This function validates SampleRecord payloads and binds the producer source tree.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import threading
import time
from typing import Any, Sequence

from .autoencoder_target_preparation import (
    _bounded_target_results, _bridge_report_telemetry, target_snapshot_config,
    unique_training_samples,
)


def prepare_legal_ir_reports(records: Sequence[Any], path: str | Path, *,
                             training_config: Any = None,
                             validation_records: Sequence[Any] = ()) -> dict[str, Any]:
    """Write one full-report bundle, preserving complete and missing outcomes.

    A returned report with adapter failures remains a native partial report.
    An escaping outer timeout produces an explicit missing report with status
    ``timeout``; no report, target, or successful adapter outcome is fabricated.
    Unexpected errors propagate. The exclusive writer does not publish a bundle
    after generator/source-validation failure. Callers may observe the bounded
    generation boundary to retain diagnostics on failed preparation attempts.
    """
    from ...logic.bridge import evaluate_legal_ir_multiview
    from ...logic.bridge.multiview import MultiViewLegalIRReport
    from .autoencoder_training_worker import SampleRecord, TrainingConfig, _JOB_LOCK, _worker_environment
    from .legal_ir_report_bundle import write_report_bundle
    from .legal_samples import build_us_code_sample
    from . import modal_autoencoder as modal

    config = training_config if training_config is not None else TrainingConfig()
    if type(config) is not TrainingConfig:
        raise TypeError("training_config must be an exact TrainingConfig")
    train, validation = tuple(records), tuple(validation_records)
    if not train or any(type(row) is not SampleRecord for row in (*train, *validation)):
        raise ValueError("report preparation requires nonempty exact SampleRecord inputs")
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("report preparation must start on the main thread")
    if not _JOB_LOCK.acquire(blocking=False):
        raise ValueError("report preparation cannot run beside another job in this process")

    started = time.perf_counter()
    try:
        with _worker_environment():
            bound_config = target_snapshot_config(config)
            sample_started = time.perf_counter()
            samples = unique_training_samples(
                [build_us_code_sample(**asdict(row)) for row in train],
                [build_us_code_sample(**asdict(row)) for row in validation],
            )
            sample_seconds = time.perf_counter() - sample_started
            intervals = []
            interval_lock = threading.Lock()
            statuses, outcomes = {}, {}

            def generate(sample):
                try:
                    report = modal._evaluate_legal_ir_multiview_with_timeout(
                        evaluate_legal_ir_multiview,
                        timeout_seconds=bound_config.target_timeout_seconds,
                        text=sample.text, bridge_names=config.legal_ir_bridge_names,
                        document_id=sample.sample_id, citation=sample.citation,
                        source=sample.source, source_embedding=sample.embedding_vector,
                        evaluate_provers=False, compiler_guidance=None, cache=False,
                    )
                except modal._LegalIRTargetTimeout as exc:
                    return sample.sample_id, None, "timeout", _bridge_report_telemetry(outer_timeout=exc)
                if report is None:
                    return sample.sample_id, None, "unavailable", _bridge_report_telemetry()
                if type(report) is not MultiViewLegalIRReport:
                    raise TypeError("report producer returned an unsupported non-native report")
                status = "ready" if not report.failures and set(report.reports) == set(report.bridge_names) else "partial"
                return sample.sample_id, report, status, _bridge_report_telemetry(report)

            def timed_generate(sample):
                call_started = time.perf_counter()
                try:
                    return generate(sample)
                finally:
                    with interval_lock:
                        intervals.append((call_started, time.perf_counter()))

            def report_records():
                generated = _bounded_target_results(timed_generate, samples, config.legal_ir_parallel_workers)
                try:
                    for sample, (sample_id, report, status, telemetry) in generated:
                        statuses[sample_id] = status
                        outcomes[sample_id] = telemetry
                        yield sample, report, status
                        del report
                    if target_snapshot_config(config) != bound_config:
                        raise ValueError("report producer changed while building bundle")
                finally:
                    generated.close()

            artifact_started = time.perf_counter()
            generated_records = report_records()
            try:
                saved = write_report_bundle(path, generated_records, config=bound_config)
            finally:
                generated_records.close()
            artifact_seconds = time.perf_counter() - artifact_started
            generation_seconds, prior_end = 0.0, 0.0
            for interval_start, interval_end in sorted(intervals):
                generation_seconds += max(0.0, interval_end - max(prior_end, interval_start))
                prior_end = max(prior_end, interval_end)
            return {
                "schema_version": "autoencoder-report-preparation-v1",
                "report_snapshot_id": saved["snapshot_id"],
                "artifact": {key: saved[key] for key in ("path", "sha256", "bytes")},
                "sample_count": len(samples),
                "report_count": sum(status in {"ready", "partial"} for status in statuses.values()),
                "statuses": statuses, "bridge_report_telemetry": outcomes,
                "status_definitions": {
                    "ready": "all requested adapters returned reports without evaluation exceptions; acceptance/proof success is not implied",
                    "partial": "a native report retains actual failures or missing adapter reports without invented failure messages",
                    "timeout": "the outer timeout escaped; no report or optimizer target was invented",
                    "unavailable": "producer returned no report; adapter outcomes are unknown",
                },
                "artifact_format": "report_bundle", "artifact_statistics": saved.get("statistics", {}),
                "maximum_pending_generation_results": min(len(samples), config.legal_ir_parallel_workers),
                "artifact_builder_retains_all_reports": False,
                "separate_target_artifact_written": False,
                "bridge_names": list(config.legal_ir_bridge_names),
                "legal_ir_evaluate_provers": False, "compiler_guidance": None,
                "legal_ir_parallel_workers": config.legal_ir_parallel_workers,
                "metric_disk_cache": 0, "metric_process_cache_used": False,
                "multiview_process_cache_used": False,
                "target_timeout_enforcement": bound_config.dependency_provenance["target_timeout_enforcement"],
                "cache_observation": "direct report generation; metric/multiview caches bypassed; OS caches uncontrolled",
                "sample_preparation_seconds": sample_seconds,
                "report_generation_seconds": generation_seconds,
                "report_generation_seconds_per_span": generation_seconds / len(samples),
                "report_generate_call_seconds": sum(end - begin for begin, end in intervals),
                "report_generation_and_artifact_seconds": artifact_seconds,
                "report_pipeline_non_generation_seconds": max(0.0, artifact_seconds - generation_seconds),
                "generation_timing_scope": "union of native producer call wall intervals; artifact encoding and validation are separate",
                "elapsed_seconds": time.perf_counter() - started,
                "source_verification_scope": "SampleRecord payloads and current package producer config; source/corpus authority must be verified by caller",
                "admitted": False,
            }
    finally:
        _JOB_LOCK.release()

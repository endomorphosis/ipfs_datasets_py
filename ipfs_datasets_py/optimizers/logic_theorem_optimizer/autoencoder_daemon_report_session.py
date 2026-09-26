"""Resident verified reports and their derived targets for native daemon use.

The runner owns consumer, bridge-list and unchanged-full-sample eligibility.
Report graphs remain privately owned mutable objects; this is neither an
arbitrary custom-consumer cache nor an admission or runtime-computation proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Sequence

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget, MultiViewLegalIRReport
from .autoencoder_daemon_target_session import DaemonTargetDescriptor
from .autoencoder_target_preparation import target_snapshot_config
from . import legal_ir_report_bundle as report_codec
from .legal_ir_target_snapshot import (
    DEFAULT_MAX_BYTES, TargetSnapshotError, _digest, _json, _parse, _sample_payload,
)


# Only structural descriptor validation is shared. The runner's distinct flags
# reject simultaneous target/report descriptors before either session opens.
DaemonReportDescriptor = DaemonTargetDescriptor


@dataclass(frozen=True)
class _Settings:
    legal_ir_bridge_names: tuple[str, ...]
    legal_ir_evaluate_provers: bool
    legal_ir_parallel_workers: int


class VerifiedDaemonReportSession:
    """Retain one complete native report selection across verified cycles.

    The report codec owns complete graph/sample/config/target validation. This
    session composes its public file verifier with the existing whole-package
    producer guard. Boundary checks cannot detect mutation restored between
    checks and do not attest Python bytecode loaded before the first check.
    Encoded expanded bytes are bounded; Python graph RSS is not.
    """

    def __init__(self, descriptor: DaemonReportDescriptor, *, bridge_names,
                 evaluate_provers: bool, parallel_workers: int,
                 max_expanded_bytes: int = DEFAULT_MAX_BYTES):
        if type(descriptor) is not DaemonReportDescriptor:
            raise TypeError("descriptor must be DaemonReportDescriptor")
        if (type(bridge_names) not in (tuple, list)
                or any(type(name) is not str or not name.strip() for name in bridge_names)
                or len(set(bridge_names)) != len(bridge_names)):
            raise TargetSnapshotError("exact ordered unique bridge names are required")
        if type(evaluate_provers) is not bool or type(parallel_workers) is not int or parallel_workers < 1:
            raise TargetSnapshotError("exact prover boolean and positive worker count are required")
        if type(max_expanded_bytes) is not int or not 1 <= max_expanded_bytes <= DEFAULT_MAX_BYTES:
            raise TargetSnapshotError("invalid requested expanded report byte bound")
        self._descriptor = descriptor
        self._settings = _Settings(tuple(bridge_names), evaluate_provers, parallel_workers)
        self._max_expanded_bytes = max_expanded_bytes
        self._thread = threading.get_ident()
        self._bundle = None
        self._config = None
        self._config_bytes = None
        self._closed = self._poisoned = self._active = False
        self._selection_result = None
        self._selection = None
        self._cycle_samples = ()
        self._cycle = self._lineage = self._failure = None
        self._counts = {"cycles_started": 0, "cycles_completed": 0,
                        "hydrations": 0, "cache_hits": 0, "skipped_cycles": 0}
        self._timings = {"guard_seconds": 0.0, "hydrate_seconds": 0.0}
        # Disabling metric bridges leaves diagnostics on their ordinary path.
        if self._settings.legal_ir_bridge_names:
            try:
                self._config = target_snapshot_config(self._settings)
                self._config_bytes = _json(self._config.to_dict())
                self._bundle = report_codec.load_report_bundle(
                    descriptor.path, expected_sha256=descriptor.sha256,
                    expected_size_bytes=descriptor.size_bytes, config=self._config,
                )
                if self._bundle.snapshot_id != descriptor.snapshot_id:
                    raise TargetSnapshotError("report bundle snapshot identity mismatch")
                self._check_boundary()
            except BaseException:
                self.close()
                raise

    def _usable(self):
        if self._closed:
            raise TargetSnapshotError("report session is closed")
        if threading.get_ident() != self._thread:
            raise TargetSnapshotError("report session must stay on its owning thread")
        if self._poisoned:
            raise TargetSnapshotError("report session is poisoned; start a fresh process")

    def _check_boundary(self):
        if self._bundle is None:
            return
        started = time.perf_counter()
        try:
            current = target_snapshot_config(self._settings)
            if _json(current.to_dict()) != self._config_bytes:
                raise TargetSnapshotError("report producer configuration changed; start a fresh process")
            self._bundle.verify_unchanged()
        finally:
            self._timings["guard_seconds"] += time.perf_counter() - started

    @staticmethod
    def _members(train_samples: Sequence[Any], validation_samples: Sequence[Any]):
        samples, identities = {}, {}
        for rows in (train_samples, validation_samples):
            for sample in rows:
                sample_id, identity = _sample_payload(sample)
                if sample_id in identities and identities[sample_id] != identity:
                    raise TargetSnapshotError("sample ID aliases different content across splits")
                samples.setdefault(sample_id, sample)
                identities[sample_id] = identity
        return tuple(samples.values()), tuple(sorted(identities.items()))

    def begin_cycle(self, train_samples, validation_samples, *, skip_reason=None):
        self._usable()
        if self._active:
            raise TargetSnapshotError("report session cycle is already active")
        if skip_reason is not None and (type(skip_reason) is not str or not skip_reason):
            raise TargetSnapshotError("skip reason must be a nonempty string")
        self._active = True
        self._counts["cycles_started"] += 1
        self._lineage = None
        self._cycle = {"number": self._counts["cycles_started"], "status": "provisional",
                       "applied": False, "cache_hit": False, "skip_reason": None,
                       "sample_count": 0, "referenced_expanded_bytes": 0}
        try:
            self._check_boundary()
            reason = "bridge_off" if not self._settings.legal_ir_bridge_names else skip_reason
            if reason is not None:
                self._skip(reason)
                return None
            train_rows, validation_rows = tuple(train_samples), tuple(validation_samples)
            samples, selection = self._members(train_rows, validation_rows)
            # Retain every input: mutating a distinct equal duplicate after
            # unioning must still prevent completion of this cycle.
            self._cycle_samples = (*train_rows, *validation_rows)
            metadata = self._bundle.selection_metadata(
                samples, config=self._config, max_expanded_bytes=self._max_expanded_bytes,
            )
            self._cycle.update(
                sample_count=len(samples), report_statuses=metadata["statuses"],
                referenced_expanded_bytes=metadata["referenced_expanded_bytes"],
            )
            if selection != self._selection:
                self._selection_result = self._selection = None
                started = time.perf_counter()
                try:
                    result = self._bundle.selection_for(
                        samples, config=self._config, max_expanded_bytes=self._max_expanded_bytes,
                    )
                finally:
                    self._timings["hydrate_seconds"] += time.perf_counter() - started
                self._counts["hydrations"] += 1
                expected = {sample.sample_id for sample in samples}
                if set(result.reports) != expected or set(result.targets) != expected:
                    raise TargetSnapshotError("report selection does not cover the exact sample union")
                for sample_id in expected:
                    report, target = result.reports[sample_id], result.targets[sample_id]
                    if (type(report) is not MultiViewLegalIRReport
                            or type(target) is not LegalIRTrainingTarget
                            or target.document is not report.document):
                        raise TargetSnapshotError("report selection must retain native shared-document targets")
                self._selection_result = result
                self._selection = selection
            else:
                self._counts["cache_hits"] += 1
                self._cycle["cache_hit"] = True
            self._cycle["applied"] = True
            self._lineage = {
                "artifact_kind": "full_report_bundle", "artifact_sha256": self._descriptor.sha256,
                "artifact_bytes": self._descriptor.size_bytes, "snapshot_id": self._descriptor.snapshot_id,
                "config_sha256": _digest(self._config.to_dict()), "selection_sha256": _digest(selection),
            }
            return self._selection_result.targets
        except BaseException as exc:
            self.abort_cycle(exc)
            raise

    @property
    def reports_for_cycle(self):
        if self._closed or self._poisoned or not self._active or not self._cycle["applied"]:
            return None
        self._usable()
        return self._selection_result.reports

    def _skip(self, reason):
        self._selection_result = self._selection = None
        self._cycle_samples = ()
        self._cycle["skip_reason"] = reason
        self._counts["skipped_cycles"] += 1

    def finish_cycle(self):
        self._usable()
        if not self._active:
            raise TargetSnapshotError("no active report session cycle")
        try:
            if self._cycle["applied"]:
                _, selection = self._members(self._cycle_samples, ())
                if selection != self._selection:
                    raise TargetSnapshotError("sample payload changed during report session cycle")
            self._check_boundary()
            self._cycle["status"] = "completed"
            self._counts["cycles_completed"] += 1
            self._active = False
            self._cycle_samples = ()
            return _parse(_json(self._cycle))
        except BaseException as exc:
            self.abort_cycle(exc)
            raise

    def abort_cycle(self, error=None):
        self._poisoned, self._active = True, False
        self._selection_result = self._selection = self._lineage = None
        self._cycle_samples = ()
        self._failure = {"exception_type": type(error).__name__ if error is not None else None}
        if self._cycle is not None:
            self._cycle["status"] = "failed"

    @property
    def lineage_identity(self):
        return _parse(_json(self._lineage))

    def summary(self):
        return _parse(_json({
            "schema_version": "daemon-full-report-session-v1", "closed": self._closed,
            "poisoned": self._poisoned, "active": self._active,
            "counts": self._counts, "timings": self._timings,
            "current_cycle": self._cycle, "failure": self._failure,
            "max_referenced_expanded_bytes": self._max_expanded_bytes,
            "bound_scope": "encoded report bytes; not a Python graph RSS bound",
            "completion_scope": "verified inputs and completed cycle; not bridge acceptance or admission",
            "artifact_kind": "full_report_bundle", "artifact": self._descriptor.to_dict(),
            "bundle_statistics": self._bundle.statistics if self._bundle is not None else None,
        }))

    def verify_shutdown(self):
        self._usable()
        if self._active:
            raise TargetSnapshotError("cannot verify shutdown with a provisional report session cycle")
        try:
            self._check_boundary()
        except BaseException as exc:
            self.abort_cycle(exc)
            raise
        return self.summary()

    def close(self):
        self._selection_result = self._selection = self._lineage = None
        self._cycle_samples = ()
        self._closed = True
        if self._bundle is not None:
            self._bundle.close()

    def __enter__(self):
        self._usable()
        return self

    def __exit__(self, *_):
        self.close()

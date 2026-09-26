"""One resident, verified full-target selection for the native daemon evaluator.

The caller owns native-evaluator and unchanged-full-sample eligibility. Returned
graphs are privately owned native inputs, not recursively immutable objects or
an arbitrary-custom-consumer cache. No target validation, grammar work, capture,
or admission is replaced here. Source guards have the existing producer scope;
they do not attest bytecode loaded before the first producer check.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from types import MappingProxyType
from typing import Any, Sequence

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from .autoencoder_target_preparation import target_snapshot_config
from . import legal_ir_target_bundle as bundle_codec
from .legal_ir_target_snapshot import (
    DEFAULT_MAX_BYTES, TargetSnapshotError, _digest, _hash, _json, _parse, _sample_payload,
)


@dataclass(frozen=True)
class DaemonTargetDescriptor:
    path: str
    sha256: str
    size_bytes: int
    snapshot_id: str

    def __post_init__(self):
        if type(self.path) is not str or not self.path:
            raise TargetSnapshotError("target bundle path is required")
        if type(self.sha256) is not str or not _hash(self.sha256):
            raise TargetSnapshotError("target bundle SHA-256 is required")
        if type(self.size_bytes) is not int or not 1 <= self.size_bytes <= DEFAULT_MAX_BYTES:
            raise TargetSnapshotError("target bundle byte count exceeds bound or is invalid")
        if (type(self.snapshot_id) is not str or not self.snapshot_id.startswith("sha256:")
                or not _hash(self.snapshot_id[7:])):
            raise TargetSnapshotError("target bundle snapshot identity is required")

    @classmethod
    def from_options(cls, path=None, sha256=None, size_bytes=None, snapshot_id=None):
        values = (path, sha256, size_bytes, snapshot_id)
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise TargetSnapshotError("all four target bundle descriptor options are required")
        return cls(path, sha256, size_bytes, snapshot_id)

    def to_dict(self):
        return {"path": self.path, "sha256": self.sha256,
                "bytes": self.size_bytes, "snapshot_id": self.snapshot_id}


@dataclass(frozen=True)
class _Settings:
    legal_ir_bridge_names: tuple[str, ...]
    legal_ir_evaluate_provers: bool
    legal_ir_parallel_workers: int


class VerifiedDaemonTargetSession:
    """Retain at most one fully hydrated selection, with explicit cycle leases.

The expanded-byte cap bounds encoded referenced targets, not Python graph RSS.
Every active cycle and shutdown checks current producer configuration and the
same immutable staged file. Concurrent mutation followed by restoration between
checks is outside this boundary-check protocol. Custom evaluators must receive
the existing live path instead of these mutable privately owned graphs.
"""

    def __init__(self, descriptor: DaemonTargetDescriptor, *, bridge_names,
                 evaluate_provers: bool, parallel_workers: int,
                 max_expanded_bytes: int = DEFAULT_MAX_BYTES):
        if type(descriptor) is not DaemonTargetDescriptor:
            raise TypeError("descriptor must be DaemonTargetDescriptor")
        if (type(bridge_names) not in (tuple, list)
                or any(type(name) is not str or not name.strip() for name in bridge_names)
                or len(set(bridge_names)) != len(bridge_names)):
            raise TargetSnapshotError("exact ordered unique bridge names are required")
        if type(evaluate_provers) is not bool or type(parallel_workers) is not int or parallel_workers < 1:
            raise TargetSnapshotError("exact prover boolean and positive worker count are required")
        if type(max_expanded_bytes) is not int or not 1 <= max_expanded_bytes <= DEFAULT_MAX_BYTES:
            raise TargetSnapshotError("invalid requested expanded target byte bound")
        self._descriptor = descriptor
        self._settings = _Settings(tuple(bridge_names), evaluate_provers, parallel_workers)
        self._max_expanded_bytes = max_expanded_bytes
        self._thread = threading.get_ident()
        self._bundle = None
        self._config = None
        self._config_bytes = None
        self._closed = False
        self._poisoned = False
        self._active = False
        self._targets = None
        self._selection = None
        self._cycle_samples = ()
        self._cycle = None
        self._lineage = None
        self._counts = {"cycles_started": 0, "cycles_completed": 0,
                        "hydrations": 0, "cache_hits": 0, "skipped_cycles": 0}
        self._timings = {"guard_seconds": 0.0, "hydrate_seconds": 0.0}
        self._failure = None
        # Bridge-off means no target consumer and no filesystem/provenance work.
        if self._settings.legal_ir_bridge_names:
            try:
                self._config = target_snapshot_config(self._settings)
                self._config_bytes = _json(self._config.to_dict())
                self._bundle = bundle_codec.load_target_bundle(
                    descriptor.path, expected_sha256=descriptor.sha256, config=self._config)
                if (self._bundle.statistics["artifact_bytes"] != descriptor.size_bytes
                        or self._bundle.snapshot_id != descriptor.snapshot_id):
                    raise TargetSnapshotError("target bundle descriptor byte count or snapshot identity mismatch")
                self._check_boundary()
            except BaseException:
                self.close()
                raise

    def _usable(self):
        if self._closed:
            raise TargetSnapshotError("target session is closed")
        if threading.get_ident() != self._thread:
            raise TargetSnapshotError("target session must stay on its owning thread")
        if self._poisoned:
            raise TargetSnapshotError("target session is poisoned; start a fresh process")

    def _check_boundary(self):
        if self._bundle is None:
            return
        started = time.perf_counter()
        try:
            current = target_snapshot_config(self._settings)
            if _json(current.to_dict()) != self._config_bytes:
                raise TargetSnapshotError("target producer configuration changed; start a fresh process")
            self._bundle._check_open()
            descriptor, info = bundle_codec._open_regular(self._descriptor.path, DEFAULT_MAX_BYTES)
            try:
                if (bundle_codec._fingerprint(info) != self._bundle._fingerprint
                        or info.st_size != self._descriptor.size_bytes):
                    raise TargetSnapshotError("target bundle pathname or file identity changed")
                bundle_codec._verify_file(descriptor, info, self._descriptor.sha256)
                self._bundle._check_open()
            finally:
                os.close(descriptor)
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
            raise TargetSnapshotError("target session cycle is already active")
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
            # Keep every caller input for the final check, including distinct
            # equal objects sharing an ID; hydrate only the deduplicated union.
            self._cycle_samples = (*train_rows, *validation_rows)
            expanded = 0
            for sample_id, identity in selection:
                row = self._bundle._records.get(sample_id)
                if row is None or row["sample_sha256"] != identity:
                    raise TargetSnapshotError("missing or changed sample payload")
                if not row["has_target"]:
                    raise TargetSnapshotError(f"sample has no injectable target: {row['status']}")
                expanded += self._bundle._shards[row["target_sha256"]]["uncompressed_bytes"]
                if expanded > self._max_expanded_bytes:
                    raise TargetSnapshotError("requested expanded target bytes exceed session bound")
            self._cycle.update(sample_count=len(samples), referenced_expanded_bytes=expanded,
                               target_statuses={key: self._bundle._records[key]["status"] for key, _ in selection})
            if selection != self._selection:
                # Release the preceding selection before hydrating its replacement.
                self._targets, self._selection = None, None
                started = time.perf_counter()
                try:
                    targets = self._bundle.targets_for(samples, config=self._config)
                finally:
                    self._timings["hydrate_seconds"] += time.perf_counter() - started
                self._counts["hydrations"] += 1
                if any(type(target) is not LegalIRTrainingTarget for target in targets.values()):
                    self._skip("non_native_target")
                    return None
                self._targets = MappingProxyType(targets)
                self._selection = selection
            else:
                self._counts["cache_hits"] += 1
                self._cycle["cache_hit"] = True
            self._cycle["applied"] = True
            self._lineage = {
                "artifact_sha256": self._descriptor.sha256,
                "artifact_bytes": self._descriptor.size_bytes,
                "snapshot_id": self._descriptor.snapshot_id,
                "config_sha256": _digest(self._config.to_dict()),
                "selection_sha256": _digest(selection),
            }
            return self._targets
        except BaseException as exc:
            self.abort_cycle(exc)
            raise

    def _skip(self, reason):
        self._targets, self._selection, self._cycle_samples = None, None, ()
        self._cycle["skip_reason"] = reason
        self._counts["skipped_cycles"] += 1

    def finish_cycle(self):
        self._usable()
        if not self._active:
            raise TargetSnapshotError("no active target session cycle")
        try:
            if self._cycle["applied"]:
                _, selection = self._members(self._cycle_samples, ())
                if selection != self._selection:
                    raise TargetSnapshotError("sample payload changed during target session cycle")
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
        self._poisoned = True
        self._active = False
        self._targets, self._selection, self._cycle_samples, self._lineage = None, None, (), None
        self._failure = {"exception_type": type(error).__name__ if error is not None else None}
        if self._cycle is not None:
            self._cycle["status"] = "failed"

    @property
    def lineage_identity(self):
        return _parse(_json(self._lineage))

    def summary(self):
        return _parse(_json({
            "schema_version": "daemon-full-target-session-v1", "closed": self._closed,
            "poisoned": self._poisoned, "active": self._active,
            "counts": self._counts, "timings": self._timings,
            "current_cycle": self._cycle, "failure": self._failure,
            "max_referenced_expanded_bytes": self._max_expanded_bytes,
            "bound_scope": "encoded target bytes; not a Python graph RSS bound",
            "artifact": self._descriptor.to_dict(),
            "bundle_statistics": self._bundle.statistics if self._bundle is not None else None,
        }))

    def verify_shutdown(self):
        self._usable()
        if self._active:
            raise TargetSnapshotError("cannot verify shutdown with a provisional target session cycle")
        try:
            self._check_boundary()
        except BaseException as exc:
            self.abort_cycle(exc)
            raise
        return self.summary()

    def close(self):
        self._targets, self._selection, self._cycle_samples, self._lineage = None, None, (), None
        self._closed = True
        if self._bundle is not None:
            self._bundle.close()

    def __enter__(self):
        self._usable()
        return self

    def __exit__(self, *_):
        self.close()

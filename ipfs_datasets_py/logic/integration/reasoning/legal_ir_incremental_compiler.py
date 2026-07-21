"""Incremental and parallel LegalIR compilation orchestration.

This module is the performance layer above the LegalIR pass manager.  It keeps
content-addressed records for external source, citation, symbol, temporal, and
pass nodes; invalidates only the affected dependency subgraph; runs independent
passes concurrently behind deterministic resource leases; and emits a replayable
summary of avoided work and speedup.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .legal_ir_pass_manager import (
    LegalIRPassDiagnostic,
    LegalIRPassDiagnosticSeverity,
    LegalIRPassKind,
    LegalIRPassManager,
    LegalIRPassSpec,
    LegalIRPassValidationError,
)


LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION: Final = "legal-ir-incremental-compiler-v1"


class LegalIRIncrementalNodeKind(str, Enum):
    """Node kinds tracked by the incremental compiler graph."""

    SOURCE = "source"
    CITATION = "citation"
    SYMBOL = "symbol"
    TEMPORAL = "temporal"
    PASS = "pass"


class LegalIRIncrementalCompileStatus(str, Enum):
    """Per-node materialization status."""

    EXECUTED = "executed"
    REUSED = "reused"
    SKIPPED = "skipped"


class LegalIRIncrementalCompilerError(ValueError):
    """Raised when incremental compilation cannot be planned or replayed."""


IncrementalPassCallable = Callable[[Mapping[str, Any]], Mapping[str, Any] | Any]


@dataclass(frozen=True)
class LegalIRResourceLease:
    """Resource capacity granted to one compilation shard."""

    lease_id: str
    requirements: Mapping[str, int]
    started_order: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "requirements": {key: int(value) for key, value in sorted(self.requirements.items())},
            "started_order": int(self.started_order),
        }


class LegalIRResourceLeaseManager:
    """Deterministic in-process resource lease manager for parallel shards."""

    def __init__(self, limits: Mapping[str, int] | None = None) -> None:
        normalized = {
            str(key): max(1, int(value))
            for key, value in dict(limits or {"cpu": 1}).items()
            if str(key)
        }
        if not normalized:
            normalized = {"cpu": 1}
        self._limits = dict(sorted(normalized.items()))
        self._active = {key: 0 for key in self._limits}
        self._max_active = {key: 0 for key in self._limits}
        self._condition = threading.Condition()
        self._counter = 0

    @property
    def limits(self) -> Mapping[str, int]:
        return dict(self._limits)

    @property
    def max_active(self) -> Mapping[str, int]:
        with self._condition:
            return dict(self._max_active)

    @contextmanager
    def lease(self, requirements: Mapping[str, int] | None = None):
        normalized = _resource_requirements(requirements)
        with self._condition:
            for name, amount in normalized.items():
                limit = self._limits.get(name)
                if limit is None:
                    raise LegalIRIncrementalCompilerError(
                        f"Resource {name!r} has no configured lease capacity."
                    )
                if amount > limit:
                    raise LegalIRIncrementalCompilerError(
                        f"Resource request {name}={amount} exceeds configured limit {limit}."
                    )
            while not self._can_acquire(normalized):
                self._condition.wait()
            for name, amount in normalized.items():
                self._active[name] += amount
                self._max_active[name] = max(self._max_active[name], self._active[name])
            self._counter += 1
            lease = LegalIRResourceLease(
                lease_id=f"lir-lease-{self._counter:08d}",
                requirements=normalized,
                started_order=self._counter,
            )
        try:
            yield lease
        finally:
            with self._condition:
                for name, amount in normalized.items():
                    self._active[name] -= amount
                self._condition.notify_all()

    def _can_acquire(self, requirements: Mapping[str, int]) -> bool:
        return all(
            self._active.get(name, 0) + amount <= self._limits.get(name, 0)
            for name, amount in requirements.items()
        )


@dataclass(frozen=True)
class LegalIRIncrementalNodeRecord:
    """Replayable record for one external or pass graph node."""

    node_id: str
    kind: str
    digest: str
    dependencies: tuple[str, ...] = ()
    status: str = LegalIRIncrementalCompileStatus.SKIPPED.value
    invalidated: bool = False
    avoided: bool = False
    pass_id: str = ""
    input_digest: str = ""
    output_digest: str = ""
    changed_fields: tuple[str, ...] = ()
    invalidated_paths: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    resource_requirements: Mapping[str, int] = field(default_factory=dict)
    lease: LegalIRResourceLease | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION

    @property
    def executed(self) -> bool:
        return self.status == LegalIRIncrementalCompileStatus.EXECUTED.value

    @property
    def reused(self) -> bool:
        return self.status == LegalIRIncrementalCompileStatus.REUSED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "avoided": bool(self.avoided),
            "changed_fields": list(self.changed_fields),
            "dependencies": list(self.dependencies),
            "digest": self.digest,
            "duration_seconds": float(self.duration_seconds),
            "input_digest": self.input_digest,
            "invalidated": bool(self.invalidated),
            "invalidated_paths": list(self.invalidated_paths),
            "kind": self.kind,
            "lease": self.lease.to_dict() if self.lease else None,
            "metadata": _json_ready(self.metadata),
            "node_id": self.node_id,
            "output_digest": self.output_digest,
            "pass_id": self.pass_id,
            "resource_requirements": {
                key: int(value) for key, value in sorted(self.resource_requirements.items())
            },
            "schema_version": self.schema_version,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRIncrementalNodeRecord":
        lease_data = data.get("lease")
        return cls(
            node_id=str(data.get("node_id") or ""),
            kind=str(data.get("kind") or ""),
            digest=str(data.get("digest") or ""),
            dependencies=tuple(_strings(data.get("dependencies", ()))),
            status=str(data.get("status") or LegalIRIncrementalCompileStatus.SKIPPED.value),
            invalidated=bool(data.get("invalidated", False)),
            avoided=bool(data.get("avoided", False)),
            pass_id=str(data.get("pass_id") or ""),
            input_digest=str(data.get("input_digest") or ""),
            output_digest=str(data.get("output_digest") or ""),
            changed_fields=tuple(_strings(data.get("changed_fields", ()))),
            invalidated_paths=tuple(_strings(data.get("invalidated_paths", ()))),
            duration_seconds=float(data.get("duration_seconds") or 0.0),
            resource_requirements={
                str(key): int(value)
                for key, value in dict(data.get("resource_requirements") or {}).items()
            },
            lease=LegalIRResourceLease(
                lease_id=str(_mapping(lease_data).get("lease_id") or ""),
                requirements={
                    str(key): int(value)
                    for key, value in dict(_mapping(lease_data).get("requirements") or {}).items()
                },
                started_order=int(_mapping(lease_data).get("started_order") or 0),
            )
            if lease_data
            else None,
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRIncrementalCompilationSnapshot:
    """Reusable incremental compiler cache state."""

    node_records: tuple[LegalIRIncrementalNodeRecord, ...]
    output_state: Mapping[str, Any]
    pass_outputs: Mapping[str, Mapping[str, Any]]
    pass_input_digests: Mapping[str, str]
    pass_output_digests: Mapping[str, str]
    pass_spec_digests: Mapping[str, str]
    external_digests: Mapping[str, str]
    compile_digest: str = ""
    schema_version: str = LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        digest = self.compile_digest or _stable_hash(
            {
                "external_digests": self.external_digests,
                "pass_output_digests": self.pass_output_digests,
                "pass_spec_digests": self.pass_spec_digests,
                "schema_version": self.schema_version,
            }
        )
        object.__setattr__(self, "compile_digest", digest)

    @property
    def records_by_node_id(self) -> Mapping[str, LegalIRIncrementalNodeRecord]:
        return {record.node_id: record for record in self.node_records}

    @property
    def records_by_pass_id(self) -> Mapping[str, LegalIRIncrementalNodeRecord]:
        return {
            record.pass_id: record
            for record in self.node_records
            if record.pass_id and record.kind == LegalIRIncrementalNodeKind.PASS.value
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "compile_digest": self.compile_digest,
            "external_digests": dict(sorted(self.external_digests.items())),
            "node_records": [record.to_dict() for record in self.node_records],
            "output_state": _json_ready(self.output_state),
            "pass_input_digests": dict(sorted(self.pass_input_digests.items())),
            "pass_output_digests": dict(sorted(self.pass_output_digests.items())),
            "pass_outputs": {
                key: _json_ready(value) for key, value in sorted(self.pass_outputs.items())
            },
            "pass_spec_digests": dict(sorted(self.pass_spec_digests.items())),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRIncrementalCompilationSnapshot":
        return cls(
            node_records=tuple(
                LegalIRIncrementalNodeRecord.from_dict(_mapping(item))
                for item in _sequence(data.get("node_records"))
            ),
            output_state=_mapping(data.get("output_state")),
            pass_outputs={
                str(key): _mapping(value)
                for key, value in dict(data.get("pass_outputs") or {}).items()
            },
            pass_input_digests={
                str(key): str(value)
                for key, value in dict(data.get("pass_input_digests") or {}).items()
            },
            pass_output_digests={
                str(key): str(value)
                for key, value in dict(data.get("pass_output_digests") or {}).items()
            },
            pass_spec_digests={
                str(key): str(value)
                for key, value in dict(data.get("pass_spec_digests") or {}).items()
            },
            external_digests={
                str(key): str(value)
                for key, value in dict(data.get("external_digests") or {}).items()
            },
            compile_digest=str(data.get("compile_digest") or ""),
            schema_version=str(data.get("schema_version") or LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRIncrementalCompileMetrics:
    """Performance summary for one incremental compile."""

    invalidated_nodes: tuple[str, ...]
    executed_nodes: tuple[str, ...]
    avoided_nodes: tuple[str, ...]
    avoided_work_units: float
    executed_work_units: float
    total_work_units: float
    avoided_work_fraction: float
    estimated_full_rebuild_seconds: float
    incremental_wall_time_seconds: float
    p95_speedup: float
    max_parallel_shards: int
    resource_lease_limits: Mapping[str, int]
    resource_lease_max_active: Mapping[str, int]
    schema_version: str = LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "avoided_nodes": list(self.avoided_nodes),
            "avoided_work_fraction": float(self.avoided_work_fraction),
            "avoided_work_units": float(self.avoided_work_units),
            "estimated_full_rebuild_seconds": float(self.estimated_full_rebuild_seconds),
            "executed_nodes": list(self.executed_nodes),
            "executed_work_units": float(self.executed_work_units),
            "incremental_wall_time_seconds": float(self.incremental_wall_time_seconds),
            "invalidated_nodes": list(self.invalidated_nodes),
            "max_parallel_shards": int(self.max_parallel_shards),
            "p95_speedup": float(self.p95_speedup),
            "resource_lease_limits": {
                key: int(value) for key, value in sorted(self.resource_lease_limits.items())
            },
            "resource_lease_max_active": {
                key: int(value) for key, value in sorted(self.resource_lease_max_active.items())
            },
            "schema_version": self.schema_version,
            "total_work_units": float(self.total_work_units),
        }


@dataclass(frozen=True)
class LegalIRIncrementalCompileResult:
    """Output of an incremental LegalIR compile."""

    snapshot: LegalIRIncrementalCompilationSnapshot
    metrics: LegalIRIncrementalCompileMetrics
    diagnostics: tuple[LegalIRPassDiagnostic, ...] = ()
    deterministic_output_order: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION

    @property
    def output_state(self) -> Mapping[str, Any]:
        return self.snapshot.output_state

    @property
    def successful(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic_output_order": list(self.deterministic_output_order),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metrics": self.metrics.to_dict(),
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "successful": self.successful,
        }


@dataclass(frozen=True)
class _ExternalNode:
    node_id: str
    kind: str
    digest: str
    payload: Any


@dataclass(frozen=True)
class _PassTaskResult:
    pass_id: str
    produced: Mapping[str, Any]
    output_values: Mapping[str, Any]
    input_digest: str
    output_digest: str
    duration_seconds: float
    changed_fields: tuple[str, ...]
    invalidated_paths: tuple[str, ...]
    lease: LegalIRResourceLease | None


class LegalIRIncrementalCompiler:
    """Incremental, parallel compiler for LegalIR pass pipelines."""

    def __init__(
        self,
        passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
        pass_functions: Mapping[str, IncrementalPassCallable] | None = None,
        *,
        max_workers: int = 1,
        resource_limits: Mapping[str, int] | None = None,
        pass_resource_requirements: Mapping[str, Mapping[str, int]] | None = None,
    ) -> None:
        self._manager = LegalIRPassManager(passes)
        validation = self._manager.validate()
        if not validation.valid:
            raise LegalIRPassValidationError(_format_diagnostics(validation.diagnostics))
        self._passes = self._manager.ordered_passes()
        self._pass_by_id = {item.pass_id: item for item in self._passes}
        self._functions = dict(pass_functions or {})
        self._max_workers = max(1, int(max_workers or 1))
        self._resource_limits = dict(resource_limits or {"cpu": self._max_workers})
        self._pass_resource_requirements = {
            str(pass_id): _resource_requirements(requirements)
            for pass_id, requirements in dict(pass_resource_requirements or {}).items()
        }
        self._dependencies, self._dependents = _pass_dependency_graph(self._passes)
        self._field_consumers = _field_consumers(self._passes)
        self._produced_fields = tuple(
            output for spec in self._passes for output in spec.declared_outputs
        )

    @property
    def ordered_pass_ids(self) -> tuple[str, ...]:
        return tuple(spec.pass_id for spec in self._passes)

    def compile(
        self,
        initial_state: Mapping[str, Any],
        *,
        previous: LegalIRIncrementalCompilationSnapshot | Mapping[str, Any] | None = None,
        sources: Mapping[str, Any] | Sequence[Any] | None = None,
        citations: Mapping[str, Any] | Sequence[Any] | None = None,
        symbols: Mapping[str, Any] | Sequence[Any] | None = None,
        temporal: Mapping[str, Any] | Sequence[Any] | None = None,
        pass_functions: Mapping[str, IncrementalPassCallable] | None = None,
    ) -> LegalIRIncrementalCompileResult:
        """Compile with cache reuse from ``previous`` when digests permit it."""

        previous_snapshot = _snapshot(previous)
        functions = {**self._functions, **dict(pass_functions or {})}
        external_nodes = _external_nodes(initial_state, sources, citations, symbols, temporal)
        external_digests = {node.node_id: node.digest for node in external_nodes}
        previous_external_digests = dict(previous_snapshot.external_digests) if previous_snapshot else {}
        changed_external = tuple(
            sorted(
                node_id
                for node_id, digest in external_digests.items()
                if previous_external_digests.get(node_id) != digest
            )
        )
        removed_external = tuple(
            sorted(node_id for node_id in previous_external_digests if node_id not in external_digests)
        )
        changed_external = tuple(sorted((*changed_external, *removed_external)))

        pass_spec_digests = {spec.pass_id: _stable_hash(spec.to_dict()) for spec in self._passes}
        previous_spec_digests = dict(previous_snapshot.pass_spec_digests) if previous_snapshot else {}
        changed_specs = tuple(
            sorted(
                pass_id
                for pass_id, digest in pass_spec_digests.items()
                if previous_spec_digests.get(pass_id) != digest
            )
        )

        candidate_passes: set[str] = set()
        if previous_snapshot is None:
            candidate_passes.update(self.ordered_pass_ids)
        else:
            for node_id in changed_external:
                candidate_passes.update(self._direct_external_consumers(node_id))
            candidate_passes.update(changed_specs)

        initial_invalidated = tuple(
            sorted(
                [
                    *changed_external,
                    *(f"pass:{pass_id}" for pass_id in changed_specs),
                    *(f"pass:{pass_id}" for pass_id in candidate_passes),
                ]
            )
        )
        invalidated_node_ids: set[str] = set(initial_invalidated)

        lease_manager = LegalIRResourceLeaseManager(self._resource_limits)
        state = _deepcopy_mapping(initial_state)
        completed: set[str] = set()
        pending: set[str] = set(self.ordered_pass_ids)
        node_records: list[LegalIRIncrementalNodeRecord] = []
        pass_outputs = dict(previous_snapshot.pass_outputs) if previous_snapshot else {}
        pass_input_digests: dict[str, str] = {}
        pass_output_digests: dict[str, str] = {}
        diagnostics: list[LegalIRPassDiagnostic] = []
        executed_nodes: list[str] = []
        avoided_nodes: list[str] = []
        speedup_samples: list[float] = []
        start = time.perf_counter()

        for node in external_nodes:
            node_records.append(
                LegalIRIncrementalNodeRecord(
                    node_id=node.node_id,
                    kind=node.kind,
                    digest=node.digest,
                    status=LegalIRIncrementalCompileStatus.REUSED.value
                    if node.node_id not in changed_external and previous_snapshot is not None
                    else LegalIRIncrementalCompileStatus.EXECUTED.value,
                    invalidated=node.node_id in changed_external,
                    avoided=node.node_id not in changed_external and previous_snapshot is not None,
                )
            )

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            while pending:
                ready = tuple(
                    sorted(
                        (
                            pass_id
                            for pass_id in pending
                            if self._dependencies.get(pass_id, set()) <= completed
                        ),
                        key=self._pass_sort_key,
                    )
                )
                if not ready:
                    raise LegalIRIncrementalCompilerError(
                        f"LegalIR pass graph contains a cycle near {sorted(pending)!r}."
                    )

                tasks: dict[Any, tuple[LegalIRPassSpec, str, bool]] = {}
                immediate: list[LegalIRIncrementalNodeRecord] = []
                batch_state = _deepcopy_mapping(state)

                for pass_id in ready:
                    spec = self._pass_by_id[pass_id]
                    input_digest = self._pass_input_digest(
                        spec,
                        batch_state,
                        external_digests,
                        pass_output_digests,
                        previous_snapshot,
                    )
                    previous_record = (
                        previous_snapshot.records_by_pass_id.get(pass_id)
                        if previous_snapshot
                        else None
                    )
                    previous_input_digest = (
                        previous_snapshot.pass_input_digests.get(pass_id, "")
                        if previous_snapshot
                        else ""
                    )
                    previous_output_digest = (
                        previous_snapshot.pass_output_digests.get(pass_id, "")
                        if previous_snapshot
                        else ""
                    )
                    cached_outputs = (
                        previous_snapshot.pass_outputs.get(pass_id, {})
                        if previous_snapshot
                        else {}
                    )
                    can_reuse = (
                        previous_snapshot is not None
                        and pass_id not in candidate_passes
                        and previous_record is not None
                        and bool(cached_outputs)
                    )
                    can_reuse_digest = (
                        previous_snapshot is not None
                        and input_digest == previous_input_digest
                        and previous_output_digest
                        and bool(cached_outputs)
                    )
                    if can_reuse or can_reuse_digest:
                        output_values = _deepcopy_mapping(cached_outputs)
                        for path, value in output_values.items():
                            _set_path(state, path, value)
                        pass_outputs[pass_id] = _json_ready(output_values)
                        pass_input_digests[pass_id] = input_digest
                        pass_output_digests[pass_id] = previous_output_digest
                        node_id = f"pass:{pass_id}"
                        avoided_nodes.append(node_id)
                        speedup_samples.append(
                            _node_baseline_seconds(previous_record, spec)
                            / 0.000001
                        )
                        immediate.append(
                            LegalIRIncrementalNodeRecord(
                                node_id=node_id,
                                kind=LegalIRIncrementalNodeKind.PASS.value,
                                digest=_stable_hash(
                                    {
                                        "input_digest": input_digest,
                                        "output_digest": previous_output_digest,
                                        "pass_id": pass_id,
                                        "spec_digest": pass_spec_digests[pass_id],
                                    }
                                ),
                                dependencies=tuple(
                                    f"pass:{dependency}"
                                    for dependency in sorted(
                                        self._dependencies.get(pass_id, set()),
                                        key=self._pass_sort_key,
                                    )
                                ),
                                status=LegalIRIncrementalCompileStatus.REUSED.value,
                                invalidated=pass_id in candidate_passes,
                                avoided=True,
                                pass_id=pass_id,
                                input_digest=input_digest,
                                output_digest=previous_output_digest,
                                duration_seconds=0.0,
                                resource_requirements=self._requirements_for(spec),
                                metadata={"reuse_reason": "input_digest_match" if can_reuse_digest else "subgraph_clean"},
                            )
                        )
                        continue

                    future = executor.submit(
                        self._run_pass_task,
                        spec,
                        batch_state,
                        input_digest,
                        functions.get(pass_id),
                        lease_manager,
                    )
                    tasks[future] = (spec, input_digest, pass_id in candidate_passes)

                for record in immediate:
                    node_records.append(record)
                    completed.add(record.pass_id)
                    pending.remove(record.pass_id)

                task_results: list[_PassTaskResult] = []
                for future in as_completed(tasks):
                    spec, _input_digest, _was_candidate = tasks[future]
                    try:
                        task_results.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - surfaced as compiler diagnostic
                        diagnostics.append(
                            LegalIRPassDiagnostic(
                                code="incremental_pass_execution_failed",
                                message=str(exc),
                                severity=LegalIRPassDiagnosticSeverity.ERROR.value,
                                pass_id=spec.pass_id,
                            )
                        )

                for result in sorted(task_results, key=lambda item: self._pass_sort_key(item.pass_id)):
                    spec = self._pass_by_id[result.pass_id]
                    previous_output_digest = (
                        previous_snapshot.pass_output_digests.get(result.pass_id, "")
                        if previous_snapshot
                        else ""
                    )
                    previous_record = (
                        previous_snapshot.records_by_pass_id.get(result.pass_id)
                        if previous_snapshot
                        else None
                    )
                    pass_outputs[result.pass_id] = _json_ready(result.output_values)
                    pass_input_digests[result.pass_id] = result.input_digest
                    pass_output_digests[result.pass_id] = result.output_digest
                    for path, value in result.output_values.items():
                        _set_path(state, path, value)
                    output_changed = result.output_digest != previous_output_digest
                    if output_changed or result.invalidated_paths:
                        changed_dependents = set(self._dependents.get(result.pass_id, set()))
                        candidate_passes.update(changed_dependents)
                        invalidated_node_ids.update(
                            f"pass:{pass_id}" for pass_id in changed_dependents
                        )
                        for path in result.invalidated_paths:
                            path_consumers = set(self._consumers_for_path(path))
                            candidate_passes.update(path_consumers)
                            invalidated_node_ids.update(
                                f"pass:{pass_id}" for pass_id in path_consumers
                            )
                    node_id = f"pass:{result.pass_id}"
                    executed_nodes.append(node_id)
                    baseline_seconds = _node_baseline_seconds(previous_record, spec)
                    speedup_samples.append(
                        baseline_seconds / max(result.duration_seconds, 0.000001)
                    )
                    node_records.append(
                        LegalIRIncrementalNodeRecord(
                            node_id=node_id,
                            kind=LegalIRIncrementalNodeKind.PASS.value,
                            digest=_stable_hash(
                                {
                                    "input_digest": result.input_digest,
                                    "output_digest": result.output_digest,
                                    "pass_id": result.pass_id,
                                    "spec_digest": pass_spec_digests[result.pass_id],
                                }
                            ),
                            dependencies=tuple(
                                f"pass:{dependency}"
                                for dependency in sorted(
                                    self._dependencies.get(result.pass_id, set()),
                                    key=self._pass_sort_key,
                                )
                            ),
                            status=LegalIRIncrementalCompileStatus.EXECUTED.value,
                            invalidated=result.pass_id in candidate_passes or output_changed,
                            avoided=False,
                            pass_id=result.pass_id,
                            input_digest=result.input_digest,
                            output_digest=result.output_digest,
                            changed_fields=result.changed_fields,
                            invalidated_paths=result.invalidated_paths,
                            duration_seconds=result.duration_seconds,
                            resource_requirements=self._requirements_for(spec),
                            lease=result.lease,
                        )
                    )
                    completed.add(result.pass_id)
                    pending.remove(result.pass_id)

        wall_time = time.perf_counter() - start
        pass_node_records = [
            record for record in node_records if record.kind == LegalIRIncrementalNodeKind.PASS.value
        ]
        total_work_units = sum(_work_units(self._pass_by_id[record.pass_id]) for record in pass_node_records)
        avoided_work_units = sum(
            _work_units(self._pass_by_id[record.pass_id]) for record in pass_node_records if record.avoided
        )
        executed_work_units = sum(
            _work_units(self._pass_by_id[record.pass_id]) for record in pass_node_records if record.executed
        )
        estimated_full = sum(
            _node_baseline_seconds(
                previous_snapshot.records_by_pass_id.get(record.pass_id) if previous_snapshot else None,
                self._pass_by_id[record.pass_id],
            )
            for record in pass_node_records
        )
        snapshot = LegalIRIncrementalCompilationSnapshot(
            node_records=tuple(sorted(node_records, key=_node_record_sort_key)),
            output_state=_json_ready(state),
            pass_outputs={key: _json_ready(value) for key, value in sorted(pass_outputs.items())},
            pass_input_digests=pass_input_digests,
            pass_output_digests=pass_output_digests,
            pass_spec_digests=pass_spec_digests,
            external_digests=external_digests,
        )
        metrics = LegalIRIncrementalCompileMetrics(
            invalidated_nodes=tuple(sorted(invalidated_node_ids)),
            executed_nodes=tuple(sorted(executed_nodes, key=_node_id_sort_key)),
            avoided_nodes=tuple(sorted(avoided_nodes, key=_node_id_sort_key)),
            avoided_work_units=float(avoided_work_units),
            executed_work_units=float(executed_work_units),
            total_work_units=float(total_work_units),
            avoided_work_fraction=(float(avoided_work_units) / float(total_work_units))
            if total_work_units
            else 0.0,
            estimated_full_rebuild_seconds=float(estimated_full),
            incremental_wall_time_seconds=float(wall_time),
            p95_speedup=_percentile(speedup_samples or [1.0], 95.0),
            max_parallel_shards=max(lease_manager.max_active.values() or [1]),
            resource_lease_limits=lease_manager.limits,
            resource_lease_max_active=lease_manager.max_active,
        )
        return LegalIRIncrementalCompileResult(
            snapshot=snapshot,
            metrics=metrics,
            diagnostics=tuple(diagnostics),
            deterministic_output_order=self.ordered_pass_ids,
        )

    def _run_pass_task(
        self,
        spec: LegalIRPassSpec,
        state: Mapping[str, Any],
        input_digest: str,
        function: IncrementalPassCallable | None,
        lease_manager: LegalIRResourceLeaseManager,
    ) -> _PassTaskResult:
        requirements = self._requirements_for(spec)
        with lease_manager.lease(requirements) as lease:
            start = time.perf_counter()
            before = _deepcopy_mapping(state)
            if function is None:
                produced = before
            else:
                produced = _payload_mapping(function(_deepcopy_mapping(before)))
            duration = time.perf_counter() - start
        output_values = _declared_outputs(produced, spec.declared_outputs)
        if not output_values:
            output_values = _declared_outputs(before, spec.declared_outputs)
        previous_values = _declared_outputs(before, spec.declared_outputs)
        changed_fields = _changed_output_fields(previous_values, output_values)
        invalidated_paths = tuple(
            _unique_text(
                path
                for rule in spec.invalidation_rules
                if rule.applies(changed_fields)
                for path in rule.invalidates
            )
        )
        output_digest = _stable_hash(output_values)
        return _PassTaskResult(
            pass_id=spec.pass_id,
            produced=produced,
            output_values=output_values,
            input_digest=input_digest,
            output_digest=output_digest,
            duration_seconds=duration,
            changed_fields=changed_fields,
            invalidated_paths=invalidated_paths,
            lease=lease,
        )

    def _pass_input_digest(
        self,
        spec: LegalIRPassSpec,
        state: Mapping[str, Any],
        external_digests: Mapping[str, str],
        current_pass_output_digests: Mapping[str, str],
        previous: LegalIRIncrementalCompilationSnapshot | None,
    ) -> str:
        dependency_output_digests: dict[str, str] = {}
        for dependency in sorted(self._dependencies.get(spec.pass_id, set()), key=self._pass_sort_key):
            dependency_output_digests[dependency] = current_pass_output_digests.get(
                dependency,
                previous.pass_output_digests.get(dependency, "") if previous else "",
            )
        return _stable_hash(
            {
                "declared_inputs": {
                    path: _get_path(state, path)
                    for path in spec.declared_inputs
                    if _has_path(state, path)
                },
                "dependency_output_digests": dependency_output_digests,
                "external_digests": {
                    key: digest
                    for key, digest in sorted(external_digests.items())
                    if spec.pass_id in self._direct_external_consumers(key)
                },
                "pass_id": spec.pass_id,
                "spec_digest": _stable_hash(spec.to_dict()),
            }
        )

    def _direct_external_consumers(self, node_id: str) -> tuple[str, ...]:
        kind = node_id.split(":", 1)[0]
        consumers: list[str] = []
        for spec in self._passes:
            if any(
                _field_belongs_to_kind(path, kind)
                and not any(
                    _path_matches(path, produced) or _path_matches(produced, path)
                    for produced in self._produced_fields
                )
                for path in spec.declared_inputs
            ):
                consumers.append(spec.pass_id)
            elif kind == LegalIRIncrementalNodeKind.SOURCE.value and not spec.declared_inputs:
                consumers.append(spec.pass_id)
        return tuple(sorted(consumers, key=self._pass_sort_key))

    def _consumers_for_path(self, path: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    pass_id
                    for watched, pass_ids in self._field_consumers.items()
                    if _path_matches(path, watched) or _path_matches(watched, path)
                    for pass_id in pass_ids
                },
                key=self._pass_sort_key,
            )
        )

    def _requirements_for(self, spec: LegalIRPassSpec) -> Mapping[str, int]:
        if spec.pass_id in self._pass_resource_requirements:
            return self._pass_resource_requirements[spec.pass_id]
        metadata_requirements = _mapping(spec.metadata.get("resource_requirements"))
        if metadata_requirements:
            return _resource_requirements(metadata_requirements)
        if spec.kind == LegalIRPassKind.HAMMER:
            return {"cpu": 1}
        return {"cpu": 1}

    def _pass_sort_key(self, pass_id: str) -> tuple[int, str]:
        spec = self._pass_by_id.get(pass_id)
        return (int(spec.order) if spec else 0, pass_id)


def compile_legal_ir_incremental(
    initial_state: Mapping[str, Any],
    pass_functions: Mapping[str, IncrementalPassCallable] | None = None,
    *,
    passes: Sequence[LegalIRPassSpec | Mapping[str, Any]] | None = None,
    previous: LegalIRIncrementalCompilationSnapshot | Mapping[str, Any] | None = None,
    sources: Mapping[str, Any] | Sequence[Any] | None = None,
    citations: Mapping[str, Any] | Sequence[Any] | None = None,
    symbols: Mapping[str, Any] | Sequence[Any] | None = None,
    temporal: Mapping[str, Any] | Sequence[Any] | None = None,
    max_workers: int = 1,
    resource_limits: Mapping[str, int] | None = None,
    pass_resource_requirements: Mapping[str, Mapping[str, int]] | None = None,
) -> LegalIRIncrementalCompileResult:
    """Convenience API for one incremental LegalIR compilation."""

    compiler = LegalIRIncrementalCompiler(
        passes,
        pass_functions,
        max_workers=max_workers,
        resource_limits=resource_limits,
        pass_resource_requirements=pass_resource_requirements,
    )
    return compiler.compile(
        initial_state,
        previous=previous,
        sources=sources,
        citations=citations,
        symbols=symbols,
        temporal=temporal,
    )


def _external_nodes(
    state: Mapping[str, Any],
    sources: Mapping[str, Any] | Sequence[Any] | None,
    citations: Mapping[str, Any] | Sequence[Any] | None,
    symbols: Mapping[str, Any] | Sequence[Any] | None,
    temporal: Mapping[str, Any] | Sequence[Any] | None,
) -> tuple[_ExternalNode, ...]:
    groups = {
        LegalIRIncrementalNodeKind.SOURCE.value: sources
        if sources is not None
        else _derived_group(state, ("raw_document", "sources", "source_map")),
        LegalIRIncrementalNodeKind.CITATION.value: citations
        if citations is not None
        else _derived_group(state, ("citation_graph", "citation_ids", "citations")),
        LegalIRIncrementalNodeKind.SYMBOL.value: symbols
        if symbols is not None
        else _derived_group(state, ("symbol_table", "symbols")),
        LegalIRIncrementalNodeKind.TEMPORAL.value: temporal
        if temporal is not None
        else _derived_group(state, ("authority_graph", "temporal_context", "temporal")),
    }
    nodes: list[_ExternalNode] = []
    for kind, payload in groups.items():
        for item_id, item in _items(payload):
            node_id = f"{kind}:{item_id}"
            nodes.append(
                _ExternalNode(
                    node_id=node_id,
                    kind=kind,
                    digest=_stable_hash({"kind": kind, "payload": item}),
                    payload=item,
                )
            )
    return tuple(sorted(nodes, key=lambda item: _node_id_sort_key(item.node_id)))


def _derived_group(state: Mapping[str, Any], paths: Sequence[str]) -> Mapping[str, Any]:
    payload = {path: _get_path(state, path) for path in paths if _has_path(state, path)}
    return {"root": payload} if payload else {}


def _items(value: Mapping[str, Any] | Sequence[Any] | None) -> tuple[tuple[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple((str(key), item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple((str(index), item) for index, item in enumerate(value))
    return (("root", value),)


def _pass_dependency_graph(
    passes: Sequence[LegalIRPassSpec],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    producers: dict[str, set[str]] = defaultdict(set)
    by_id = {spec.pass_id: spec for spec in passes}
    dependencies: dict[str, set[str]] = {spec.pass_id: set() for spec in passes}
    dependents: dict[str, set[str]] = {spec.pass_id: set() for spec in passes}
    for spec in passes:
        for output in spec.declared_outputs:
            producers[output].add(spec.pass_id)
    for spec in passes:
        for dependency in spec.depends_on:
            if dependency in by_id:
                dependencies[spec.pass_id].add(dependency)
        for declared_input in spec.declared_inputs:
            for output, pass_ids in producers.items():
                if _path_matches(declared_input, output) or _path_matches(output, declared_input):
                    dependencies[spec.pass_id].update(
                        pass_id for pass_id in pass_ids if pass_id != spec.pass_id
                    )
        for other in passes:
            if other.pass_id == spec.pass_id:
                continue
            for rule in other.invalidation_rules:
                if any(
                    _path_matches(invalidated, declared_input)
                    or _path_matches(declared_input, invalidated)
                    for invalidated in rule.invalidates
                    for declared_input in spec.declared_inputs
                ):
                    dependencies[spec.pass_id].add(other.pass_id)
    for pass_id, deps in dependencies.items():
        for dependency in deps:
            dependents.setdefault(dependency, set()).add(pass_id)
    return dependencies, dependents


def _field_consumers(passes: Sequence[LegalIRPassSpec]) -> dict[str, set[str]]:
    consumers: dict[str, set[str]] = defaultdict(set)
    for spec in passes:
        for declared_input in spec.declared_inputs:
            consumers[declared_input].add(spec.pass_id)
    return consumers


def _declared_outputs(payload: Mapping[str, Any], outputs: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in outputs:
        if _has_path(payload, path):
            result[path] = _json_ready(_get_path(payload, path))
    return result


def _changed_output_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, ...]:
    changed = [
        path
        for path in sorted(set(before) | set(after))
        if _json_ready(before.get(path)) != _json_ready(after.get(path))
    ]
    return tuple(changed)


def _field_belongs_to_kind(path: str, kind: str) -> bool:
    path = str(path or "")
    if kind == LegalIRIncrementalNodeKind.SOURCE.value:
        return any(
            _path_matches(path, candidate)
            for candidate in (
                "raw_document",
                "normalized_document",
                "source_map",
                "source_document_id",
                "sources",
            )
        )
    if kind == LegalIRIncrementalNodeKind.CITATION.value:
        return any(
            _path_matches(path, candidate)
            for candidate in ("citation", "citation_graph", "citation_ids", "citations")
        )
    if kind == LegalIRIncrementalNodeKind.SYMBOL.value:
        return any(
            _path_matches(path, candidate)
            for candidate in ("symbol", "symbol_table", "symbols")
        )
    if kind == LegalIRIncrementalNodeKind.TEMPORAL.value:
        return any(
            _path_matches(path, candidate)
            for candidate in (
                "authority_graph",
                "temporal",
                "temporal_context",
                "temporal_window",
            )
        )
    return False


def _work_units(spec: LegalIRPassSpec) -> float:
    metadata = dict(spec.metadata or {})
    try:
        return max(0.0, float(metadata.get("work_units", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def _node_baseline_seconds(
    record: LegalIRIncrementalNodeRecord | None,
    spec: LegalIRPassSpec,
) -> float:
    if record is not None and record.duration_seconds > 0:
        return float(record.duration_seconds)
    metadata = dict(spec.metadata or {})
    try:
        estimate = float(metadata.get("estimated_seconds", metadata.get("work_units", 1.0)))
    except (TypeError, ValueError):
        estimate = 1.0
    return max(0.000001, estimate)


def _resource_requirements(requirements: Mapping[str, Any] | None) -> dict[str, int]:
    normalized = {
        str(key): max(1, int(value))
        for key, value in dict(requirements or {"cpu": 1}).items()
        if str(key)
    }
    return dict(sorted(normalized.items())) if normalized else {"cpu": 1}


def _snapshot(
    value: LegalIRIncrementalCompilationSnapshot | Mapping[str, Any] | None,
) -> LegalIRIncrementalCompilationSnapshot | None:
    if value is None:
        return None
    if isinstance(value, LegalIRIncrementalCompilationSnapshot):
        return value
    return LegalIRIncrementalCompilationSnapshot.from_dict(value)


def _node_record_sort_key(record: LegalIRIncrementalNodeRecord) -> tuple[int, str]:
    return _node_id_sort_key(record.node_id)


def _node_id_sort_key(node_id: str) -> tuple[int, str]:
    text = str(node_id)
    if text.startswith("source:"):
        return (0, text)
    if text.startswith("citation:"):
        return (1, text)
    if text.startswith("symbol:"):
        return (2, text)
    if text.startswith("temporal:"):
        return (3, text)
    if text.startswith("pass:"):
        return (4, text)
    return (9, text)


def _percentile(values: Sequence[float], percentile: float) -> float:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return 1.0
    if len(finite) == 1:
        return finite[0]
    rank = (len(finite) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return finite[int(rank)]
    weight = rank - lower
    return finite[lower] * (1.0 - weight) + finite[upper] * weight


def _path_matches(path: str, pattern: str) -> bool:
    path = str(path or "")
    pattern = str(pattern or "")
    if not path or not pattern:
        return False
    if pattern == "*":
        return True
    if path == pattern or path.startswith(pattern + "."):
        return True
    path_parts = path.split(".")
    pattern_parts = pattern.split(".")
    if len(pattern_parts) > len(path_parts):
        return False
    for actual, expected in zip(path_parts, pattern_parts):
        if expected == "*":
            continue
        if actual != expected:
            return False
    return True


def _has_path(value: Mapping[str, Any], path: str) -> bool:
    current: Any = value
    for part in str(path).split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False
    return True


def _get_path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in str(path).split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            return None
    return current


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    current: dict[str, Any] = target
    parts = str(path).split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = _json_ready(value)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _payload_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _deepcopy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(value))


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value) if str(item))


def _unique_text(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if hasattr(value, "__dict__"):
        return _json_ready(vars(value))
    return str(value)


def _format_diagnostics(diagnostics: Sequence[LegalIRPassDiagnostic]) -> str:
    return "; ".join(
        f"{diagnostic.code}:{diagnostic.pass_id or '-'}:{diagnostic.field_path or '-'}"
        for diagnostic in diagnostics
        if diagnostic.error
    ) or "LegalIR incremental compiler validation failed"


__all__ = [
    "LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION",
    "IncrementalPassCallable",
    "LegalIRIncrementalCompilationSnapshot",
    "LegalIRIncrementalCompileMetrics",
    "LegalIRIncrementalCompileResult",
    "LegalIRIncrementalCompileStatus",
    "LegalIRIncrementalCompiler",
    "LegalIRIncrementalCompilerError",
    "LegalIRIncrementalNodeKind",
    "LegalIRIncrementalNodeRecord",
    "LegalIRResourceLease",
    "LegalIRResourceLeaseManager",
    "compile_legal_ir_incremental",
]

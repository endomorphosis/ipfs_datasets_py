"""Bridge deterministic Abby audio worksets to the canonical P2P task queue.

This module is intentionally an adapter, not another queue implementation.
It translates the execution-free :mod:`ipfs_datasets_py.voice.workset` DAG
into the shared ``ipfs_accelerate_py`` voice-job contracts and submits those
contracts to the canonical DuckDB-backed ``TaskQueue``.

The bridge preserves the complete workset lineage in every task payload.
Replaying a workset is safe: contract task IDs are content hashes and an
existing, byte-equivalent task is returned instead of being inserted again.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from ipfs_accelerate_py.voice_jobs.contracts import (
    ArtifactDescriptor,
    VoiceASRJob,
    VoiceAudioValidationJob,
    VoiceJobLineage,
    VoiceJobResult,
    VoiceTTSJob,
    voice_job_from_payload,
)
from ipfs_accelerate_py.voice_jobs.regeneration import (
    RegenerationDispatchManifest,
    RegenerationEndpointContract,
    RegenerationRunnerPolicy,
    VoiceRegenerationRunner,
    build_regeneration_dispatch_manifest,
)

from ...voice.workset import AudioWorkItem, AudioWorkOperation, VoiceAudioWorkset

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_CANONICAL_RESULT_FIELDS = frozenset(
    {
        "artifacts",
        "error",
        "lineage",
        "provider_receipt",
        "quality_metrics",
        "schema_version",
        "status",
        "task_id",
        "task_type",
    }
)
_RESULT_ENVELOPE_FIELDS = frozenset(
    {
        "executor_worker_id",
        "logs",
        "model_id",
        "progress",
        "session_id",
    }
)
_CANONICAL_LINEAGE_FIELDS = frozenset(
    {
        "depends_on_task_ids",
        "manifest_id",
        "policy_id",
        "publication_id",
        "source_manifest_id",
        "subject_id",
        "subject_schema_version",
        "task_id",
        "work_item_id",
        "workset_id",
    }
)
_LINEAGE_ENVELOPE_FIELDS = frozenset({"model_id"})
_PROGRESS_ENVELOPE_FIELDS = frozenset(
    {
        "cancel_reason",
        "cancelled_at",
        "heartbeat_ts",
        "last_release_reason",
        "last_release_ts",
        "mesh",
        "phase",
        "release_count",
        "task_type",
        "ts",
        "worker_id",
    }
)
_LOG_ENVELOPE_FIELDS = frozenset({"message", "stream", "ts"})


class VoiceJobBridgeError(RuntimeError):
    """Base error raised at the datasets-to-accelerate boundary."""


class VoiceJobConflictError(VoiceJobBridgeError):
    """A deterministic task ID already exists with different content."""


class VoiceJobReceiptError(VoiceJobBridgeError):
    """A terminal queue receipt does not match its submitted job lineage."""


class _CanonicalQueue(Protocol):
    """The small part of the canonical TaskQueue used by this adapter."""

    def submit(
        self,
        *,
        task_type: str,
        model_name: str,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> str: ...

    def get(self, task_id: str) -> dict[str, Any] | None: ...

    def cancel(self, *, task_id: str, reason: str | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class VoiceWorksetBridgeConfig:
    """Output-affecting provider settings used to materialize job contracts."""

    tts_provider: str = "abby_indextts"
    tts_model_name: str = "Publicus/IndexTTS-2-Demo"
    tts_voice: str = "abby"
    tts_provider_version: str = "1"
    tts_codec: str = "wav"
    tts_sample_rate_hz: int = 24_000
    tts_channels: int = 1
    tts_generation_settings: Mapping[str, Any] = field(default_factory=dict)
    asr_provider: str = "huggingface"
    asr_model_name: str = "openai/whisper-base"
    asr_provider_version: str = "1"
    asr_decoding_settings: Mapping[str, Any] = field(default_factory=dict)
    asr_retention_policy: str = "result"
    validation_provider: str = "local"
    validation_model_name: str = "abby-audio-validator"
    validation_policy_version: str = "1"
    validation_policy: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = (
            "tts_provider",
            "tts_model_name",
            "tts_voice",
            "tts_provider_version",
            "tts_codec",
            "asr_provider",
            "asr_model_name",
            "asr_provider_version",
            "asr_retention_policy",
            "validation_provider",
            "validation_model_name",
            "validation_policy_version",
        )
        for name in required:
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{name} must be a non-empty canonical string")
        if (
            isinstance(self.tts_sample_rate_hz, bool)
            or not isinstance(self.tts_sample_rate_hz, int)
            or self.tts_sample_rate_hz <= 0
        ):
            raise ValueError("tts_sample_rate_hz must be a positive integer")
        if (
            isinstance(self.tts_channels, bool)
            or not isinstance(self.tts_channels, int)
            or self.tts_channels <= 0
        ):
            raise ValueError("tts_channels must be a positive integer")
        for name in (
            "tts_generation_settings",
            "asr_decoding_settings",
            "validation_policy",
        ):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} must be a mapping")
            # Copy caller-owned mappings so later mutation cannot silently
            # alter a job identity between planning and submission.
            object.__setattr__(self, name, MappingProxyType(dict(value)))


@dataclass(frozen=True, slots=True)
class VoiceJobSubmission:
    """One work-item-to-task binding returned by the bridge."""

    work_item_id: str
    task_id: str
    task_type: str
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class VoiceWorksetSubmission:
    """Submission receipt for a complete deterministic workset DAG."""

    workset_id: str
    jobs: tuple[VoiceJobSubmission, ...]

    @property
    def task_ids_by_work_item(self) -> dict[str, str]:
        return {job.work_item_id: job.task_id for job in self.jobs}


VoiceJob = VoiceTTSJob | VoiceASRJob | VoiceAudioValidationJob


def _artifact_from_work_item(item: AudioWorkItem) -> ArtifactDescriptor | None:
    descriptor = item.audio
    if descriptor is None:
        return None
    return ArtifactDescriptor.from_dict(descriptor.to_dict())


def _lineage(
    *,
    workset: VoiceAudioWorkset,
    manifest_id: str,
    item: AudioWorkItem,
    dependency_task_ids: Sequence[str] = (),
) -> VoiceJobLineage:
    return VoiceJobLineage(
        workset_id=workset.workset_id,
        source_manifest_id=workset.source_manifest_id,
        manifest_id=manifest_id,
        work_item_id=item.work_id,
        subject_id=item.subject_id,
        subject_schema_version=item.subject_schema_version,
        policy_id=workset.policy_id,
        depends_on_task_ids=tuple(dependency_task_ids),
    )


def jobs_from_voice_workset(
    workset: VoiceAudioWorkset,
    *,
    config: VoiceWorksetBridgeConfig | None = None,
) -> tuple[VoiceJob, ...]:
    """Translate a validated workset into a dependency-ordered job tuple.

    Workset dependency IDs identify planning records. This function replaces
    them with the deterministic contract task IDs that workers and receipts
    use. Existing-audio revalidation retains its immutable artifact descriptor;
    generated-audio jobs reference their upstream task until that task returns
    the immutable descriptor.
    """

    if not isinstance(workset, VoiceAudioWorkset):
        raise TypeError("workset must be a VoiceAudioWorkset")
    selected = config or VoiceWorksetBridgeConfig()
    task_id_by_work_id: dict[str, str] = {}
    audio_task_id_by_subject: dict[tuple[str, str], str] = {}
    jobs: list[VoiceJob] = []

    manifests = (
        workset.tts_manifest,
        workset.asr_manifest,
        workset.validation_manifest,
    )
    for manifest in manifests:
        for item in manifest.items:
            try:
                dependency_task_ids = tuple(
                    task_id_by_work_id[work_id] for work_id in item.depends_on
                )
            except KeyError as exc:  # defensive: VoiceAudioWorkset normally rejects this
                raise VoiceJobBridgeError(
                    f"work item {item.work_id!r} has an unresolved dependency {exc.args[0]!r}"
                ) from exc
            source_audio = _artifact_from_work_item(item)
            source_task_id = ""
            if item.operation in {
                AudioWorkOperation.ASR,
                AudioWorkOperation.VALIDATE,
            } and source_audio is None:
                source_key = (item.subject_id, item.locale)
                source_task_id = audio_task_id_by_subject.get(source_key, "")
                if not source_task_id:
                    raise VoiceJobBridgeError(
                        f"work item {item.work_id!r} has no immutable or generated audio source"
                    )
                dependency_task_ids = tuple(
                    sorted({*dependency_task_ids, source_task_id})
                )

            lineage = _lineage(
                workset=workset,
                manifest_id=manifest.manifest_id,
                item=item,
                dependency_task_ids=dependency_task_ids,
            )

            if item.operation is AudioWorkOperation.TTS:
                job: VoiceJob = VoiceTTSJob(
                    spoken_text=item.spoken_text,
                    locale=item.locale,
                    provider=selected.tts_provider,
                    model_name=selected.tts_model_name,
                    voice=selected.tts_voice,
                    provider_version=selected.tts_provider_version,
                    lineage=lineage,
                    codec=selected.tts_codec,
                    sample_rate_hz=selected.tts_sample_rate_hz,
                    channels=selected.tts_channels,
                    generation_settings=dict(selected.tts_generation_settings),
                )
            elif item.operation is AudioWorkOperation.ASR:
                job = VoiceASRJob(
                    source_audio=source_audio,
                    source_task_id=source_task_id,
                    provider=selected.asr_provider,
                    model_name=selected.asr_model_name,
                    provider_version=selected.asr_provider_version,
                    lineage=lineage,
                    purpose="dataset_asr_validation",
                    locale=item.locale,
                    decoding_settings=dict(selected.asr_decoding_settings),
                    retention_policy=selected.asr_retention_policy,
                )
            elif item.operation is AudioWorkOperation.VALIDATE:
                job = VoiceAudioValidationJob(
                    source_audio=source_audio,
                    source_task_id=source_task_id,
                    model_name=selected.validation_model_name,
                    lineage=lineage,
                    validation_policy=dict(selected.validation_policy),
                    provider=selected.validation_provider,
                    policy_version=selected.validation_policy_version,
                )
            else:  # pragma: no cover - the workset enum prevents this
                raise VoiceJobBridgeError(f"unsupported audio operation {item.operation!r}")

            task_id_by_work_id[item.work_id] = job.task_id
            if item.operation is AudioWorkOperation.TTS:
                source_key = (item.subject_id, item.locale)
                previous = audio_task_id_by_subject.setdefault(source_key, job.task_id)
                if previous != job.task_id:
                    raise VoiceJobBridgeError(
                        f"subject {item.subject_id!r} has multiple generated audio sources"
                    )
            jobs.append(job)

    return tuple(jobs)


def regeneration_tts_jobs_from_voice_workset(
    workset: VoiceAudioWorkset,
    *,
    config: VoiceWorksetBridgeConfig | None = None,
) -> tuple[VoiceTTSJob, ...]:
    """Return only the deterministic synthesis stage of a voice workset.

    The complete workset still contains ASR and validation jobs.  The endpoint
    regeneration runner is intentionally limited to synthesis: downstream
    workers resolve its immutable artifact receipts before ASR or validation
    can be admitted.
    """

    return tuple(
        job
        for job in jobs_from_voice_workset(workset, config=config)
        if isinstance(job, VoiceTTSJob)
    )


def build_voice_regeneration_dispatch(
    workset: VoiceAudioWorkset,
    *,
    endpoint_contract: RegenerationEndpointContract | Mapping[str, Any],
    config: VoiceWorksetBridgeConfig | None = None,
    policy: RegenerationRunnerPolicy | None = None,
) -> RegenerationDispatchManifest:
    """Project ``workset`` into a bounded, deterministic no-dispatch manifest.

    This function does not construct a queue and does not call a provider.
    Live authorization remains a separate runtime input to
    :class:`VoiceRegenerationRunner`.
    """

    jobs = regeneration_tts_jobs_from_voice_workset(workset, config=config)
    return build_regeneration_dispatch_manifest(
        jobs,
        endpoint_contract=endpoint_contract,
        policy=policy,
    )


def run_voice_regeneration_workset(
    workset: VoiceAudioWorkset,
    *,
    runner: VoiceRegenerationRunner,
    endpoint_contract: RegenerationEndpointContract | Mapping[str, Any],
    config: VoiceWorksetBridgeConfig | None = None,
    policy: RegenerationRunnerPolicy | None = None,
    dispatch_authorized: bool = False,
) -> dict[str, Any]:
    """Build and execute a resumable synthesis manifest through ``runner``."""

    if not isinstance(runner, VoiceRegenerationRunner):
        raise TypeError("runner must be a VoiceRegenerationRunner")
    manifest = build_voice_regeneration_dispatch(
        workset,
        endpoint_contract=endpoint_contract,
        config=config,
        policy=policy,
    )
    return runner.run(manifest, dispatch_authorized=dispatch_authorized)


class VoiceJobBridge:
    """Submit, observe, cancel, and ingest canonical voice jobs."""

    def __init__(
        self,
        *,
        queue: _CanonicalQueue | None = None,
        queue_path: str | None = None,
        poll_interval_s: float = 0.05,
    ) -> None:
        if queue is not None and queue_path is not None:
            raise ValueError("pass queue or queue_path, not both")
        if isinstance(poll_interval_s, bool) or poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")
        if queue is None:
            from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue

            queue = TaskQueue(queue_path)
        self._queue = queue
        self._poll_interval_s = float(poll_interval_s)

    @property
    def queue(self) -> _CanonicalQueue:
        return self._queue

    @staticmethod
    def _assert_equivalent_existing(
        existing: Mapping[str, Any],
        *,
        job: VoiceJob,
        payload: Mapping[str, Any],
    ) -> None:
        same = (
            existing.get("task_id") == job.task_id
            and existing.get("task_type") == job.task_type
            and existing.get("model_name") == job.model_name
            and existing.get("payload") == payload
        )
        if not same:
            raise VoiceJobConflictError(
                f"task ID {job.task_id} already exists with different canonical content"
            )

    def submit(self, job: VoiceJob) -> VoiceJobSubmission:
        """Submit one job once, returning the existing row on exact replay."""

        if not isinstance(job, VoiceTTSJob | VoiceASRJob | VoiceAudioValidationJob):
            raise TypeError("job must be a canonical voice job contract")
        payload = job.to_payload()
        existing = self._queue.get(job.task_id)
        if existing is not None:
            self._assert_equivalent_existing(existing, job=job, payload=payload)
            return VoiceJobSubmission(
                work_item_id=job.lineage.work_item_id,
                task_id=job.task_id,
                task_type=job.task_type,
                status=str(existing.get("status") or ""),
                replayed=True,
            )

        try:
            submit_with_outcome = getattr(self._queue, "submit_with_outcome", None)
            if callable(submit_with_outcome):
                submitted_id, replayed = submit_with_outcome(
                    task_type=job.task_type,
                    model_name=job.model_name,
                    payload=payload,
                    task_id=job.task_id,
                )
            else:
                submitted_id = self._queue.submit(
                    task_type=job.task_type,
                    model_name=job.model_name,
                    payload=payload,
                    task_id=job.task_id,
                )
                replayed = False
        except Exception:
            # A concurrent submitter may have won the primary-key race.
            existing = self._queue.get(job.task_id)
            if existing is None:
                raise
            self._assert_equivalent_existing(existing, job=job, payload=payload)
            return VoiceJobSubmission(
                work_item_id=job.lineage.work_item_id,
                task_id=job.task_id,
                task_type=job.task_type,
                status=str(existing.get("status") or ""),
                replayed=True,
            )
        if submitted_id != job.task_id:
            raise VoiceJobBridgeError(
                f"canonical queue changed deterministic task ID {job.task_id!r} "
                f"to {submitted_id!r}"
            )
        if replayed:
            existing = self._queue.get(job.task_id)
            if existing is None:
                raise VoiceJobBridgeError(
                    f"canonical queue reported replay for missing task {job.task_id!r}"
                )
            self._assert_equivalent_existing(existing, job=job, payload=payload)
            status = str(existing.get("status") or "")
        else:
            status = "queued"
        return VoiceJobSubmission(
            work_item_id=job.lineage.work_item_id,
            task_id=job.task_id,
            task_type=job.task_type,
            status=status,
            replayed=replayed,
        )

    def submit_workset(
        self,
        workset: VoiceAudioWorkset,
        *,
        config: VoiceWorksetBridgeConfig | None = None,
    ) -> VoiceWorksetSubmission:
        jobs = jobs_from_voice_workset(workset, config=config)
        receipts = tuple(self.submit(job) for job in jobs)
        return VoiceWorksetSubmission(workset_id=workset.workset_id, jobs=receipts)

    def status(self, task_id: str) -> dict[str, Any] | None:
        """Return the canonical queue row for ``task_id``."""

        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id is required")
        return self._queue.get(task_id)

    def wait(self, task_id: str, *, timeout_s: float = 60.0) -> dict[str, Any] | None:
        """Poll until a task is terminal or the timeout expires."""

        if isinstance(timeout_s, bool) or timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        deadline = time.monotonic() + float(timeout_s)
        while True:
            task = self.status(task_id)
            if task is None or str(task.get("status") or "").lower() in _TERMINAL_STATUSES:
                return task
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return task
            time.sleep(min(self._poll_interval_s, remaining))

    def cancel(self, task_id: str, *, reason: str | None = None) -> bool:
        """Cancel a queued job using the canonical queue state transition."""

        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id is required")
        return bool(self._queue.cancel(task_id=task_id, reason=reason))

    def ingest_receipt(
        self,
        task_id: str,
        *,
        require_terminal: bool = True,
    ) -> VoiceJobResult:
        """Parse a queue result and prove it belongs to the submitted lineage."""

        task = self.status(task_id)
        if task is None:
            raise VoiceJobReceiptError(f"task {task_id!r} does not exist")
        return _parse_and_verify_receipt(
            task_id=task_id,
            task=task,
            require_terminal=require_terminal,
        )


def _canonical_envelope_text(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
    ):
        raise ValueError(f"{field_name} must be a non-empty canonical string")
    return value


def _finite_non_negative_number(value: Any, *, field_name: str) -> None:
    valid = (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    ) or (
        isinstance(value, float)
        and math.isfinite(value)
        and value >= 0
    )
    if not valid:
        raise ValueError(f"{field_name} must be a finite non-negative number")


def _extract_canonical_result_payload(
    result_payload: Mapping[str, Any],
    *,
    request: VoiceJob,
) -> dict[str, Any]:
    """Remove only verified queue metadata from a canonical voice result.

    ``TaskQueue`` intentionally merges heartbeat/log state into the final
    result, while the generic worker stamps execution metadata and augments
    its transport lineage.  Those fields are not part of
    :class:`VoiceJobResult`; accepting arbitrary extensions would weaken its
    strict contract.  This extractor therefore recognizes a closed envelope,
    validates every available binding, and returns only canonical result
    fields for the contract parser.
    """

    supplied_fields = set(result_payload)
    allowed_fields = _CANONICAL_RESULT_FIELDS | _RESULT_ENVELOPE_FIELDS
    unknown_fields = supplied_fields - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(repr(item) for item in unknown_fields))
        raise ValueError(f"unknown voice result envelope fields: {names}")

    model_id = result_payload.get("model_id")
    if model_id is not None:
        bound_model_id = _canonical_envelope_text(
            model_id,
            field_name="result.model_id",
        )
        if bound_model_id != request.model_name:
            raise ValueError("result.model_id does not match the requested model")

    executor_worker_id = result_payload.get("executor_worker_id")
    bound_worker_id = ""
    if executor_worker_id is not None:
        bound_worker_id = _canonical_envelope_text(
            executor_worker_id,
            field_name="result.executor_worker_id",
        )

    session_id = result_payload.get("session_id")
    if session_id is not None:
        _canonical_envelope_text(session_id, field_name="result.session_id")

    progress = result_payload.get("progress")
    if progress is not None:
        if not isinstance(progress, Mapping):
            raise ValueError("result.progress must be a mapping")
        unknown_progress = set(progress) - _PROGRESS_ENVELOPE_FIELDS
        if unknown_progress:
            names = ", ".join(sorted(repr(item) for item in unknown_progress))
            raise ValueError(f"unknown voice progress envelope fields: {names}")
        progress_task_type = progress.get("task_type")
        if progress_task_type is not None:
            if (
                _canonical_envelope_text(
                    progress_task_type,
                    field_name="result.progress.task_type",
                )
                != request.task_type
            ):
                raise ValueError(
                    "result.progress.task_type does not match the requested task type"
                )
        progress_worker = progress.get("worker_id")
        if progress_worker is not None:
            progress_worker_id = _canonical_envelope_text(
                progress_worker,
                field_name="result.progress.worker_id",
            )
            if bound_worker_id and progress_worker_id != bound_worker_id:
                raise ValueError(
                    "result.progress.worker_id does not match executor_worker_id"
                )
        for field_name in (
            "cancelled_at",
            "heartbeat_ts",
            "last_release_ts",
            "ts",
        ):
            if field_name in progress:
                _finite_non_negative_number(
                    progress[field_name],
                    field_name=f"result.progress.{field_name}",
                )
        if "release_count" in progress and (
            isinstance(progress["release_count"], bool)
            or not isinstance(progress["release_count"], int)
            or progress["release_count"] < 0
        ):
            raise ValueError(
                "result.progress.release_count must be a non-negative integer"
            )
        if "mesh" in progress and not isinstance(progress["mesh"], bool):
            raise ValueError("result.progress.mesh must be a boolean")
        for field_name in (
            "cancel_reason",
            "last_release_reason",
            "phase",
        ):
            if field_name in progress:
                _canonical_envelope_text(
                    progress[field_name],
                    field_name=f"result.progress.{field_name}",
                )

    logs = result_payload.get("logs")
    if logs is not None:
        if not isinstance(logs, list) or len(logs) > 2_000:
            raise ValueError("result.logs must be a bounded list")
        for index, entry in enumerate(logs):
            if not isinstance(entry, Mapping) or set(entry) != _LOG_ENVELOPE_FIELDS:
                raise ValueError(
                    f"result.logs[{index}] must match the canonical log envelope"
                )
            _finite_non_negative_number(
                entry["ts"],
                field_name=f"result.logs[{index}].ts",
            )
            _canonical_envelope_text(
                entry["stream"],
                field_name=f"result.logs[{index}].stream",
            )
            if not isinstance(entry["message"], str):
                raise ValueError(f"result.logs[{index}].message must be a string")

    canonical = {
        field_name: result_payload[field_name]
        for field_name in _CANONICAL_RESULT_FIELDS
        if field_name in result_payload
    }
    lineage = canonical.get("lineage")
    if isinstance(lineage, Mapping):
        unknown_lineage = set(lineage) - (
            _CANONICAL_LINEAGE_FIELDS | _LINEAGE_ENVELOPE_FIELDS
        )
        if unknown_lineage:
            names = ", ".join(sorted(repr(item) for item in unknown_lineage))
            raise ValueError(f"unknown voice lineage envelope fields: {names}")
        lineage_model_id = lineage.get("model_id")
        if lineage_model_id is not None and (
            _canonical_envelope_text(
                lineage_model_id,
                field_name="result.lineage.model_id",
            )
            != request.model_name
        ):
            raise ValueError(
                "result.lineage.model_id does not match the requested model"
            )
        canonical["lineage"] = {
            field_name: lineage[field_name]
            for field_name in _CANONICAL_LINEAGE_FIELDS
            if field_name in lineage
        }
    return canonical


def _parse_and_verify_receipt(
    *,
    task_id: str,
    task: Mapping[str, Any],
    require_terminal: bool,
) -> VoiceJobResult:
    """Strictly parse a receipt from the canonical queue row."""

    status = str(task.get("status") or "").lower()
    if require_terminal and status not in _TERMINAL_STATUSES:
        raise VoiceJobReceiptError(f"task {task_id!r} is not terminal")
    result_payload = task.get("result")
    if not isinstance(result_payload, Mapping):
        raise VoiceJobReceiptError(f"task {task_id!r} has no structured result receipt")
    request_payload = task.get("payload")
    if not isinstance(request_payload, Mapping):
        raise VoiceJobReceiptError(f"task {task_id!r} has no structured request payload")
    try:
        request = voice_job_from_payload(request_payload)
        canonical_result_payload = _extract_canonical_result_payload(
            result_payload,
            request=request,
        )
        result = VoiceJobResult.from_payload(canonical_result_payload)
    except (TypeError, ValueError) as exc:
        raise VoiceJobReceiptError(f"task {task_id!r} has an invalid voice receipt") from exc

    request_lineage = request.lineage.to_dict()
    result_lineage = result.lineage.to_dict()
    if (
        task.get("task_id") != task_id
        or task_id != request.task_id
        or task.get("task_type") != request.task_type
        or task.get("model_name") != request.model_name
        or result.task_id != task_id
        or result.task_type != request.task_type
        or result.status != status
        or result_lineage != request_lineage
    ):
        raise VoiceJobReceiptError(
            f"task {task_id!r} receipt does not match its request lineage"
        )
    return result


def submit_voice_workset(
    workset: VoiceAudioWorkset,
    *,
    bridge: VoiceJobBridge | None = None,
    queue: _CanonicalQueue | None = None,
    queue_path: str | None = None,
    config: VoiceWorksetBridgeConfig | None = None,
) -> VoiceWorksetSubmission:
    """Convenience entry point for deterministic workset submission."""

    if bridge is not None and (queue is not None or queue_path is not None):
        raise ValueError("pass bridge or queue/queue_path, not both")
    selected_bridge = bridge or VoiceJobBridge(queue=queue, queue_path=queue_path)
    return selected_bridge.submit_workset(workset, config=config)


__all__ = [
    "VoiceJobBridge",
    "VoiceJobBridgeError",
    "VoiceJobConflictError",
    "VoiceJobReceiptError",
    "VoiceJobSubmission",
    "VoiceWorksetBridgeConfig",
    "VoiceWorksetSubmission",
    "build_voice_regeneration_dispatch",
    "jobs_from_voice_workset",
    "regeneration_tts_jobs_from_voice_workset",
    "run_voice_regeneration_workset",
    "submit_voice_workset",
]

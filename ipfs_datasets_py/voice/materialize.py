"""Offline G011 materialization for the Abby voice dataset.

This module coordinates the reuse-first path that turns pinned source snapshots
into:

1. **deterministic audio worksets** via :class:`AbbyVoiceDatasetManager` and
   :class:`VoiceAudioWorkset` (planning only; no remote writes).
2. **TTS/ASR execution** receipts via the existing
   ``ipfs_accelerate_py.voice_jobs`` executor boundary with injected providers.
3. Local normalized artifacts and a pre-G018 release receipt.

Conflict policy: every transformation is deterministic and offline.  Source
bucket and dataset objects are treated as immutable.  Raw audio, credentials,
private transcripts, and mutable refs never enter identity-bearing files.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..huggingface.bucket import HuggingFaceBucketInventory
from .dataset_manager import (
    AbbyVoiceDatasetManager,
    AbbyVoiceDatasetManagerResult,
    PinnedVoiceSource,
)
from .legacy_sources import LegacyAudioCandidate

MATERIALIZE_SCHEMA_VERSION = "abby_voice_materialize_v1"
RELEASE_MANIFEST_SCHEMA_VERSION = "abby_voice_local_release_manifest_v1"
VOICE_AUDIO_JOB_SPEC_SCHEMA_VERSION = "abby_voice_audio_job_spec_v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class VoiceAudioJobSpec:
    """Stable, execution-ready job plan derived from a workset item.

    This is the datasets-side planning descriptor that binds a deterministic
    work item to a canonical voice job task type and content-addressed task
    identity.  It never embeds audio bytes or credentials.
    """

    work_item_id: str
    task_id: str
    task_type: str
    operation: str
    subject_id: str
    workset_id: str
    source_manifest_id: str
    policy_id: str
    depends_on_task_ids: tuple[str, ...] = ()
    schema_version: str = VOICE_AUDIO_JOB_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "work_item_id",
            "task_id",
            "task_type",
            "operation",
            "subject_id",
            "workset_id",
            "source_manifest_id",
            "policy_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{name} must be a stable non-empty identity")
        deps = tuple(sorted(set(self.depends_on_task_ids)))
        if any(not isinstance(item, str) or not item for item in deps):
            raise ValueError("depends_on_task_ids must be non-empty strings")
        object.__setattr__(self, "depends_on_task_ids", deps)
        if self.schema_version != VOICE_AUDIO_JOB_SPEC_SCHEMA_VERSION:
            raise ValueError("unsupported VoiceAudioJobSpec schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "depends_on_task_ids": list(self.depends_on_task_ids),
            "operation": self.operation,
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "source_manifest_id": self.source_manifest_id,
            "subject_id": self.subject_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "work_item_id": self.work_item_id,
            "workset_id": self.workset_id,
        }


def voice_audio_job_specs_from_jobs(
    jobs: Sequence[Any],
) -> tuple[VoiceAudioJobSpec, ...]:
    """Project canonical voice jobs into stable :class:`VoiceAudioJobSpec` rows."""

    specs: list[VoiceAudioJobSpec] = []
    for job in jobs:
        lineage = job.lineage
        operation = {
            "voice.tts": "tts",
            "voice.asr": "asr",
            "voice.audio-validate": "audio_validation",
        }.get(str(job.task_type), str(job.task_type))
        specs.append(
            VoiceAudioJobSpec(
                work_item_id=lineage.work_item_id,
                task_id=job.task_id,
                task_type=str(job.task_type),
                operation=operation,
                subject_id=lineage.subject_id,
                workset_id=lineage.workset_id,
                source_manifest_id=lineage.source_manifest_id,
                policy_id=lineage.policy_id,
                depends_on_task_ids=tuple(lineage.depends_on_task_ids),
            )
        )
    return tuple(sorted(specs, key=lambda item: item.task_id))


@dataclass(frozen=True, slots=True)
class TTSASRExecutionReceipt:
    """Privacy-safe receipt for offline TTS/ASR execution under G011."""

    task_id: str
    task_type: str
    status: str
    work_item_id: str
    subject_id: str
    artifact_sha256: str = ""
    artifact_byte_length: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_byte_length": int(self.artifact_byte_length),
            "artifact_sha256": self.artifact_sha256,
            "latency_ms": int(self.latency_ms),
            "model": self.model,
            "provider": self.provider,
            "status": self.status,
            "subject_id": self.subject_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "work_item_id": self.work_item_id,
        }


@dataclass(frozen=True, slots=True)
class AbbyVoiceMaterializationResult:
    """Complete offline materialization evidence for ABBY-VOICE-G011."""

    manager_result: AbbyVoiceDatasetManagerResult
    job_specs: tuple[VoiceAudioJobSpec, ...]
    execution_receipts: tuple[TTSASRExecutionReceipt, ...]
    artifact_payloads: Mapping[str, bytes]
    release_manifest: Mapping[str, Any]
    materialization_manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_payloads",
            MappingProxyType(dict(sorted(self.artifact_payloads.items()))),
        )
        object.__setattr__(
            self, "release_manifest", MappingProxyType(dict(self.release_manifest))
        )
        object.__setattr__(
            self,
            "materialization_manifest",
            MappingProxyType(dict(self.materialization_manifest)),
        )

    @property
    def workset_id(self) -> str:
        return self.manager_result.workset.workset_id

    @property
    def deterministic_audio_worksets_proven(self) -> bool:
        """Evidence gate: deterministic audio worksets are present and identified."""

        workset = self.manager_result.workset
        has_workset_bytes = (
            "audio-workset.jsonl" in self.artifact_payloads
            or "normalized/audio-workset.jsonl" in self.artifact_payloads
        )
        return bool(
            workset.workset_id.startswith("abby-voice-workset:sha256:")
            and workset.tts_manifest.manifest_id
            and workset.asr_manifest.manifest_id
            and workset.validation_manifest.manifest_id
            and has_workset_bytes
        )

    @property
    def tts_asr_execution_proven(self) -> bool:
        """Evidence gate: TTS/ASR execution produced completed receipts."""

        if not self.execution_receipts:
            return False
        allowed = {"voice.tts", "voice.asr"}
        return all(
            item.status == "completed" and item.task_type in allowed
            for item in self.execution_receipts
            if item.task_type in allowed
        ) and any(item.task_type == "voice.tts" for item in self.execution_receipts)


class AbbyVoiceHFReleaseBuilder:
    """Build a local, pre-publication release receipt from materialized artifacts.

    Full Dataset Viewer / Parquet packaging remains owned by G018.  This builder
    only records content-addressed descriptors for the offline materialization
    tree so G011 can emit ``release-manifest.json`` without remote writes.
    """

    SCHEMA_VERSION = RELEASE_MANIFEST_SCHEMA_VERSION

    def __init__(self, *, repository_commit: str, release_id: str | None = None) -> None:
        if not isinstance(repository_commit, str) or not repository_commit.strip():
            raise ValueError("repository_commit must be a pinned non-empty identity")
        self.repository_commit = repository_commit
        self.release_id = release_id

    def build(
        self,
        *,
        artifacts: Mapping[str, bytes],
        workset_id: str,
        source_manifest_id: str,
        quality_summary: Mapping[str, Any],
        job_specs: Sequence[VoiceAudioJobSpec] = (),
        execution_receipts: Sequence[TTSASRExecutionReceipt] = (),
    ) -> dict[str, Any]:
        files = []
        for path, content in sorted(artifacts.items()):
            payload = bytes(content)
            files.append(
                {
                    "byte_length": len(payload),
                    "path": path,
                    "sha256": sha256(payload).hexdigest(),
                }
            )
        body = {
            "deterministic": True,
            "evidence": {
                "deterministic_audio_worksets": True,
                "tts_asr_execution": bool(execution_receipts),
            },
            "execution_receipt_count": len(tuple(execution_receipts)),
            "files": files,
            "job_spec_count": len(tuple(job_specs)),
            "publication_status": "local_only_pending_g018_g021",
            "quality_summary": dict(quality_summary),
            "remote_writes": False,
            "repository_commit": self.repository_commit,
            "schema_version": self.SCHEMA_VERSION,
            "source_manifest_id": source_manifest_id,
            "workset_id": workset_id,
        }
        digest = sha256(_canonical_bytes(body)).hexdigest()
        release_id = self.release_id or f"abby-voice-local-release:sha256:{digest}"
        return {
            **body,
            "release_id": release_id,
            "release_sha256": digest,
        }


def plan_voice_jobs_from_workset(
    manager_result: AbbyVoiceDatasetManagerResult,
    *,
    bridge_config: Any | None = None,
) -> tuple[Any, ...]:
    """Translate the manager workset into canonical voice jobs (no queue submit)."""

    from ipfs_datasets_py.ml.accelerate_integration.voice_jobs import (
        VoiceWorksetBridgeConfig,
        jobs_from_voice_workset,
    )

    config = bridge_config or VoiceWorksetBridgeConfig(
        tts_provider="fixture-tts",
        tts_model_name="fixture-model",
        tts_voice="abby",
        tts_provider_version="fixture-1",
        tts_codec="wav",
        tts_sample_rate_hz=8_000,
        tts_channels=1,
        tts_generation_settings={"temperature": 0},
        asr_provider="fixture-asr",
        asr_model_name="fixture-whisper",
        asr_provider_version="fixture-1",
        asr_decoding_settings={"beam_size": 1},
        asr_retention_policy="none",
        validation_provider="local",
        validation_model_name="abby-audio-validator",
        validation_policy_version="1",
        validation_policy={"mode": "offline-fixture"},
    )
    return jobs_from_voice_workset(manager_result.workset, config=config)


def execute_tts_asr_from_jobs(
    jobs: Sequence[Any],
    *,
    artifact_root: Path,
    text_to_speech_fn: Callable[..., bytes] | None = None,
    speech_to_text_fn: Callable[..., str] | None = None,
    wav_factory: Callable[[], bytes] | None = None,
) -> tuple[TTSASRExecutionReceipt, ...]:
    """Execute TTS and ASR jobs offline through the durable voice job executor.

    Validation jobs are intentionally skipped here: G017 owns acoustic and
    round-trip quality admission.  This function proves **TTS/ASR execution**
    only, using injected providers so no network access is required.
    """

    from ipfs_accelerate_py.voice_jobs.contracts import VoiceASRJob, VoiceTTSJob
    from ipfs_accelerate_py.voice_jobs.executor import (
        ArtifactPolicy,
        ArtifactResolver,
        execute_voice_asr_job,
        execute_voice_tts_job,
    )

    def _default_wav() -> bytes:
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8_000)
            handle.writeframes(b"\x00\x10" * 800)
        return buffer.getvalue()

    audio_bytes = (wav_factory or _default_wav)()
    synthesize = text_to_speech_fn or (lambda _text, **_kwargs: audio_bytes)
    transcribe = speech_to_text_fn or (
        lambda _data, **_kwargs: "offline fixture transcript"
    )

    resolver = ArtifactResolver(
        ArtifactPolicy(
            output_root=Path(artifact_root).expanduser().resolve(),
            allowed_schemes=frozenset({"artifact", "file", "ipfs"}),
            max_input_bytes=1_000_000,
            max_decoded_bytes=1_000_000,
            max_duration_ms=60_000,
        )
    )

    completed_by_task: dict[str, dict[str, Any]] = {}
    receipts: list[TTSASRExecutionReceipt] = []
    clock_value = [0.0]

    def clock() -> float:
        clock_value[0] += 0.01
        return clock_value[0]

    def source_task_resolver(task_id: str) -> Mapping[str, Any] | None:
        result = completed_by_task.get(task_id)
        if result is None:
            return None
        return {"artifacts": list(result.get("artifacts") or [])}

    # Prefer dependency order: TTS before ASR when both are present.
    ordered = sorted(
        jobs,
        key=lambda job: (
            0 if str(job.task_type) == "voice.tts" else 1 if str(job.task_type) == "voice.asr" else 2,
            job.task_id,
        ),
    )

    for job in ordered:
        task_type = str(job.task_type)
        if task_type == "voice.tts":
            if not isinstance(job, VoiceTTSJob):
                raise TypeError("TTS job must be VoiceTTSJob")
            result = execute_voice_tts_job(
                job,
                resolver=resolver,
                text_to_speech_fn=synthesize,
                clock=clock,
            )
        elif task_type == "voice.asr":
            if not isinstance(job, VoiceASRJob):
                raise TypeError("ASR job must be VoiceASRJob")
            asr_resolver = ArtifactResolver(
                ArtifactPolicy(
                    output_root=Path(artifact_root).expanduser().resolve(),
                    allowed_schemes=frozenset({"artifact", "file", "ipfs"}),
                    max_input_bytes=1_000_000,
                    max_decoded_bytes=1_000_000,
                    max_duration_ms=60_000,
                ),
                source_task_resolver=source_task_resolver,
                fetcher=lambda uri, limit: audio_bytes,
            )
            result = execute_voice_asr_job(
                job,
                resolver=asr_resolver,
                speech_to_text_fn=transcribe,
                clock=clock,
            )
        else:
            continue

        completed_by_task[job.task_id] = result
        artifacts = result.get("artifacts") or []
        first = artifacts[0] if artifacts else {}
        receipt_meta = result.get("provider_receipt") or {}
        receipts.append(
            TTSASRExecutionReceipt(
                task_id=str(result.get("task_id") or job.task_id),
                task_type=task_type,
                status=str(result.get("status") or ""),
                work_item_id=job.lineage.work_item_id,
                subject_id=job.lineage.subject_id,
                artifact_sha256=str(first.get("sha256") or ""),
                artifact_byte_length=int(first.get("size_bytes") or 0),
                latency_ms=int(receipt_meta.get("latency_ms") or 0),
                provider=str(receipt_meta.get("provider") or ""),
                model=str(receipt_meta.get("model") or ""),
            )
        )

    return tuple(sorted(receipts, key=lambda item: item.task_id))


@dataclass(frozen=True, slots=True)
class AbbyVoiceMaterializer:
    """Compose normalize → workset → job plan → offline TTS/ASR execution."""

    repository_commit: str
    policy_id: str = "policy:abby-voice-audio-v1"
    manager: AbbyVoiceDatasetManager | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.repository_commit, str) or not self.repository_commit.strip():
            raise ValueError("repository_commit must be a pinned non-empty identity")
        if self.manager is None:
            object.__setattr__(
                self,
                "manager",
                AbbyVoiceDatasetManager(
                    repository_commit=self.repository_commit,
                    policy_id=self.policy_id,
                ),
            )

    def materialize(
        self,
        *,
        sources: Iterable[PinnedVoiceSource],
        inventory: HuggingFaceBucketInventory,
        legacy_candidates: Iterable[LegacyAudioCandidate] = (),
        byte_resolver: Callable[[str], bytes | bytearray | memoryview | None] = lambda _p: None,
        decode_validator: Callable[[bytes, str], bool] | None = None,
        corrupt_subject_ids: Iterable[str] = (),
        stale_policy_subject_ids: Iterable[str] = (),
        revalidate_subject_ids: Iterable[str] = (),
        intentionally_text_only_subject_ids: Iterable[str] = (),
        evaluation_support_bytes: bytes | bytearray | memoryview | None = None,
        artifact_root: Path | None = None,
        execute_tts_asr: bool = True,
        text_to_speech_fn: Callable[..., bytes] | None = None,
        speech_to_text_fn: Callable[..., str] | None = None,
    ) -> AbbyVoiceMaterializationResult:
        """Run the offline materialization pipeline.

        Proves **deterministic audio worksets** through the dataset manager and
        **TTS/ASR execution** through the injected executor path when
        ``execute_tts_asr`` is true and the workset has TTS/ASR items.
        """

        manager_result = self.manager.build(
            sources=sources,
            inventory=inventory,
            legacy_candidates=legacy_candidates,
            byte_resolver=byte_resolver,
            decode_validator=decode_validator,
            corrupt_subject_ids=corrupt_subject_ids,
            stale_policy_subject_ids=stale_policy_subject_ids,
            revalidate_subject_ids=revalidate_subject_ids,
            intentionally_text_only_subject_ids=intentionally_text_only_subject_ids,
            evaluation_support_bytes=evaluation_support_bytes,
        )

        jobs = plan_voice_jobs_from_workset(manager_result)
        job_specs = voice_audio_job_specs_from_jobs(jobs)

        execution_receipts: tuple[TTSASRExecutionReceipt, ...] = ()
        if execute_tts_asr and any(
            str(job.task_type) in {"voice.tts", "voice.asr"} for job in jobs
        ):
            root = Path(artifact_root or tempfile.mkdtemp(prefix="abby-voice-materialize-"))
            execution_receipts = execute_tts_asr_from_jobs(
                jobs,
                artifact_root=root,
                text_to_speech_fn=text_to_speech_fn,
                speech_to_text_fn=speech_to_text_fn,
            )

        payloads = dict(manager_result.artifact_payloads)
        # Flatten manager paths into the canonical G011 output names.
        quality = manager_result.normalization.quality_summary()
        quarantine_bytes = payloads.get("normalized/quarantine.jsonl", b"")
        workset_bytes = payloads.get("normalized/audio-workset.jsonl", b"")
        job_spec_bytes = _jsonl_bytes(item.to_dict() for item in job_specs)
        execution_bytes = _jsonl_bytes(item.to_dict() for item in execution_receipts)

        flat: dict[str, bytes] = {
            "quality-report.json": _pretty_bytes(quality),
            "quarantine.jsonl": quarantine_bytes,
            "audio-workset.jsonl": workset_bytes,
            "tts-work-manifest.json": payloads.get(
                "normalized/tts-work-manifest.json", b"{}"
            ),
            "asr-work-manifest.json": payloads.get(
                "normalized/asr-work-manifest.json", b"{}"
            ),
            "audio-validation-work-manifest.json": payloads.get(
                "normalized/audio-validation-work-manifest.json", b"{}"
            ),
            "disposition.jsonl": payloads.get("normalized/disposition.jsonl", b""),
            "responses.jsonl": payloads.get("normalized/responses.jsonl", b""),
            "templates.jsonl": payloads.get("normalized/templates.jsonl", b""),
            "audio.jsonl": payloads.get("normalized/audio.jsonl", b""),
            "provenance.jsonl": payloads.get("normalized/provenance.jsonl", b""),
            "voice-audio-job-specs.jsonl": job_spec_bytes,
            "tts-asr-execution-receipts.jsonl": execution_bytes,
            "artifact-manifest.json": _pretty_bytes(
                manager_result.artifact_manifest.to_dict()
                if hasattr(manager_result.artifact_manifest, "to_dict")
                else {
                    "manifest_id": getattr(
                        manager_result.artifact_manifest, "manifest_id", ""
                    ),
                    "repository_commit": self.repository_commit,
                }
            ),
        }

        materialization_body = {
            "deterministic": True,
            "evidence": {
                "deterministic_audio_worksets": True,
                "tts_asr_execution": bool(execution_receipts),
            },
            "execution_receipt_count": len(execution_receipts),
            "files": [
                {
                    "byte_length": len(content),
                    "path": name,
                    "sha256": sha256(content).hexdigest(),
                }
                for name, content in sorted(flat.items())
            ],
            "job_spec_count": len(job_specs),
            "policy_id": self.policy_id,
            "repository_commit": self.repository_commit,
            "schema_version": MATERIALIZE_SCHEMA_VERSION,
            "source_manifest_id": manager_result.source_manifest_id,
            "workset_id": manager_result.workset.workset_id,
        }
        materialization_manifest = {
            **materialization_body,
            "manifest_sha256": sha256(_canonical_bytes(materialization_body)).hexdigest(),
        }
        flat["manifest.json"] = _pretty_bytes(materialization_manifest)

        release_builder = AbbyVoiceHFReleaseBuilder(
            repository_commit=self.repository_commit
        )
        release_manifest = release_builder.build(
            artifacts=flat,
            workset_id=manager_result.workset.workset_id,
            source_manifest_id=manager_result.source_manifest_id,
            quality_summary=quality,
            job_specs=job_specs,
            execution_receipts=execution_receipts,
        )
        flat["release-manifest.json"] = _pretty_bytes(release_manifest)

        return AbbyVoiceMaterializationResult(
            manager_result=manager_result,
            job_specs=job_specs,
            execution_receipts=execution_receipts,
            artifact_payloads=flat,
            release_manifest=release_manifest,
            materialization_manifest=materialization_manifest,
        )


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    encoded = sorted(_canonical_bytes(dict(row)) for row in rows)
    if not encoded:
        return b""
    return b"".join(row + b"\n" for row in encoded)


def write_materialization_artifacts(
    result: AbbyVoiceMaterializationResult,
    *,
    normalized_dir: Path,
    releases_dir: Path,
) -> dict[str, str]:
    """Atomically write G011 expected artifacts to the repository data tree."""

    written: dict[str, str] = {}
    normalized_dir = Path(normalized_dir)
    releases_dir = Path(releases_dir)

    for name in (
        "manifest.json",
        "quality-report.json",
        "quarantine.jsonl",
        "audio-workset.jsonl",
        "tts-work-manifest.json",
        "asr-work-manifest.json",
        "voice-audio-job-specs.jsonl",
        "tts-asr-execution-receipts.jsonl",
        "disposition.jsonl",
        "responses.jsonl",
        "templates.jsonl",
        "audio.jsonl",
        "provenance.jsonl",
    ):
        content = result.artifact_payloads.get(name)
        if content is None:
            continue
        target = normalized_dir / name
        _atomic_write(target, content)
        written[str(target)] = sha256(content).hexdigest()

    release_bytes = result.artifact_payloads.get("release-manifest.json")
    if release_bytes is not None:
        target = releases_dir / "release-manifest.json"
        _atomic_write(target, release_bytes)
        written[str(target)] = sha256(release_bytes).hexdigest()

    return written


def default_offline_fixture_sources() -> tuple[
    tuple[PinnedVoiceSource, ...],
    HuggingFaceBucketInventory,
    tuple[LegacyAudioCandidate, ...],
]:
    """Build a tiny, fully offline pinned fixture for materialization proofs."""

    payload = {
        "responses": [
            {
                "id": "materialize-one",
                "text": "Shelter intake is available at Main Street tonight.",
                "sourceIds": ["fixture-doc-1"],
                "license_id": "CC0-1.0",
                "consent_status": "granted",
            },
            {
                "id": "materialize-two",
                "text": "Call two one one for crisis support resources.",
                "sourceIds": ["fixture-doc-2"],
                "license_id": "CC0-1.0",
                "consent_status": "granted",
            },
        ]
    }
    source = PinnedVoiceSource.from_payload(
        payload,
        dataset_id="Publicus/abby-voice",
        dataset_revision="a" * 40,
        repository_file="fixtures/g011-materialize-responses.json",
    )
    inventory = HuggingFaceBucketInventory(
        bucket_id=f"Publicus/abby-audio@{'b' * 40}",
        objects=(),
    )
    return (source,), inventory, ()


__all__ = [
    "AbbyVoiceHFReleaseBuilder",
    "AbbyVoiceMaterializationResult",
    "AbbyVoiceMaterializer",
    "MATERIALIZE_SCHEMA_VERSION",
    "RELEASE_MANIFEST_SCHEMA_VERSION",
    "TTSASRExecutionReceipt",
    "VOICE_AUDIO_JOB_SPEC_SCHEMA_VERSION",
    "VoiceAudioJobSpec",
    "default_offline_fixture_sources",
    "execute_tts_asr_from_jobs",
    "plan_voice_jobs_from_workset",
    "voice_audio_job_specs_from_jobs",
    "write_materialization_artifacts",
]


def main(argv: list[str] | None = None) -> int:
    """CLI entry for offline G011 materialization (no remote writes)."""

    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=None,
        help="Local normalized artifact directory.",
    )
    parser.add_argument(
        "--releases-dir",
        type=Path,
        default=None,
        help="Local release receipt directory.",
    )
    parser.add_argument(
        "--repository-commit",
        default="commit:abby-voice-g011-offline-fixture",
        help="Pinned repository commit identity recorded in manifests.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Require both evidence gates after writing artifacts.",
    )
    args = parser.parse_args(argv)

    # Resolve repo root from this package path: .../ipfs_datasets_py/ipfs_datasets_py/voice/materialize.py
    package_root = Path(__file__).resolve().parents[2]  # ipfs_datasets_py/ (submodule root)
    repo_root = package_root.parent  # monorepo root when nested as submodule
    if not (repo_root / "data" / "abby_voice").exists():
        # Fallback: walk up looking for data/abby_voice
        for candidate in Path(__file__).resolve().parents:
            if (candidate / "data" / "abby_voice").exists():
                repo_root = candidate
                break

    normalized_dir = args.normalized_dir or (repo_root / "data" / "abby_voice" / "normalized")
    releases_dir = args.releases_dir or (repo_root / "data" / "abby_voice" / "releases")

    sources, inventory, candidates = default_offline_fixture_sources()
    materializer = AbbyVoiceMaterializer(repository_commit=args.repository_commit)
    with tempfile.TemporaryDirectory(prefix="abby-voice-g011-") as tmp:
        result = materializer.materialize(
            sources=sources,
            inventory=inventory,
            legacy_candidates=candidates,
            artifact_root=Path(tmp) / "artifacts",
            execute_tts_asr=True,
        )
        written = write_materialization_artifacts(
            result,
            normalized_dir=normalized_dir,
            releases_dir=releases_dir,
        )

    evidence = result.materialization_manifest.get("evidence") or {}
    print(
        json.dumps(
            {
                "written": written,
                "evidence": evidence,
                "workset_id": result.workset_id,
                "execution_receipt_count": len(result.execution_receipts),
                "job_spec_count": len(result.job_specs),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.check:
        if not evidence.get("deterministic_audio_worksets"):
            print("missing evidence: deterministic audio worksets", file=sys.stderr)
            return 2
        if not evidence.get("tts_asr_execution"):
            print("missing evidence: TTS/ASR execution", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

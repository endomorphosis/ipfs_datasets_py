"""Reusable deterministic manager for pinned Abby voice dataset sources."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from ..huggingface.bucket import HuggingFaceBucketInventory
from ..huggingface.snapshot import HuggingFaceSnapshot
from ..logic.ir_core.artifacts import Artifact, ArtifactManifest, ArtifactRole
from ..logic.ir_core.provenance import ConfigBinding, ProducerBinding
from .graphrag import SlottedResponseIndex
from .legacy_sources import (
    LegacyAudioCandidate,
    LegacyAudioReconciliation,
    reconcile_legacy_audio_candidates,
)
from .normalize import AbbyVoiceDatasetNormalizer, NormalizationResult
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceDatasetBundle,
    validate_bundle,
)
from .workset import VoiceAudioWorkset

ABBY_VOICE_DATASET_MANAGER_VERSION = "1.0.0"
ABBY_VOICE_DISPOSITION_SCHEMA_VERSION = "abby_voice_disposition_v1"
ABBY_VOICE_EVALUATION_PENDING_SCHEMA = "abby_voice_evaluation_support_v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _jsonl(values: Iterable[Mapping[str, Any]]) -> bytes:
    rows = sorted((_canonical_bytes(value) for value in values))
    return b"".join(row + b"\n" for row in rows)


@dataclass(frozen=True, slots=True)
class PinnedVoiceSource:
    """A pinned Hugging Face snapshot plus its already-fetched JSON bytes."""

    snapshot: HuggingFaceSnapshot
    source_bytes: bytes
    payload: Mapping[str, Any] | Sequence[Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, HuggingFaceSnapshot):
            raise TypeError("snapshot must be a HuggingFaceSnapshot")
        raw = bytes(self.source_bytes)
        if len(raw) != self.snapshot.expected_size_bytes:
            raise ValueError("source byte length does not match pinned snapshot")
        if sha256(raw).hexdigest() != self.snapshot.expected_sha256:
            raise ValueError("source SHA-256 does not match pinned snapshot")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"pinned Abby source must be UTF-8 JSON: {exc}") from exc
        if not isinstance(payload, Mapping | list):
            raise ValueError("pinned Abby source JSON must be an object or array")
        object.__setattr__(self, "source_bytes", raw)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any] | Sequence[Any],
        *,
        dataset_id: str,
        dataset_revision: str,
        repository_file: str,
        download_producer: str = "producer:abby-voice-fixture",
    ) -> "PinnedVoiceSource":
        """Create an exact snapshot for deterministic offline callers and tests."""

        raw = _canonical_bytes(payload)
        snapshot = HuggingFaceSnapshot(
            dataset_id=dataset_id,
            dataset_revision=dataset_revision,
            repository_file=repository_file,
            expected_sha256=sha256(raw).hexdigest(),
            expected_size_bytes=len(raw),
            download_producer=download_producer,
        )
        return cls(snapshot=snapshot, source_bytes=raw)


@dataclass(frozen=True, slots=True)
class DatasetDisposition:
    source_ref: str
    source_sha256: str
    status: str
    reason: str
    schema_version: str = ABBY_VOICE_DISPOSITION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, str]:
        return {
            "reason": self.reason,
            "schema_version": self.schema_version,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class AbbyVoiceDatasetManagerResult:
    normalization: NormalizationResult
    bundle: AbbyVoiceDatasetBundle
    graphrag_index: SlottedResponseIndex
    legacy_reconciliation: LegacyAudioReconciliation
    workset: VoiceAudioWorkset
    dispositions: tuple[DatasetDisposition, ...]
    artifact_manifest: ArtifactManifest
    artifact_payloads: Mapping[str, bytes]
    source_manifest_id: str
    evaluation_support_artifact: Artifact | None = None

    def __post_init__(self) -> None:
        dispositions = tuple(sorted(self.dispositions, key=lambda item: item.source_ref))
        refs = [item.source_ref for item in dispositions]
        if len(refs) != len(set(refs)):
            raise ValueError("dataset disposition source_ref values must be unique")
        object.__setattr__(self, "dispositions", dispositions)
        object.__setattr__(
            self,
            "artifact_payloads",
            MappingProxyType(dict(sorted(self.artifact_payloads.items()))),
        )

    @property
    def four_config_bundle(self) -> dict[str, tuple[Any, ...]]:
        return {
            ABBY_VOICE_RESPONSE_V2: self.bundle.responses,
            ABBY_VOICE_TEMPLATE_V2: self.bundle.templates,
            ABBY_VOICE_AUDIO_V2: self.bundle.audio,
            ABBY_VOICE_PROVENANCE_V2: self.bundle.provenance,
        }

    def disposition_bytes(self) -> bytes:
        return _jsonl(item.to_dict() for item in self.dispositions)


class AbbyVoiceDatasetManager:
    """Compose normalization, exact legacy linking, GraphRAG, and work planning.

    Construction and :meth:`build` are offline and side-effect free.  Callers
    supply already-fetched pinned bytes and an injected audio byte resolver.
    """

    def __init__(
        self,
        *,
        repository_commit: str,
        policy_id: str = "policy:abby-voice-audio-v1",
        normalizer: AbbyVoiceDatasetNormalizer | None = None,
        index_factory: Callable[..., SlottedResponseIndex] | None = None,
    ) -> None:
        if not isinstance(repository_commit, str) or not repository_commit.strip():
            raise ValueError("repository_commit must be a pinned non-empty identity")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a stable non-empty identity")
        self.repository_commit = repository_commit
        self.policy_id = policy_id
        self.normalizer = normalizer or AbbyVoiceDatasetNormalizer()
        self.index_factory = index_factory or SlottedResponseIndex.from_rows

    def build(
        self,
        *,
        sources: Iterable[PinnedVoiceSource],
        inventory: HuggingFaceBucketInventory,
        legacy_candidates: Iterable[LegacyAudioCandidate] = (),
        byte_resolver: Callable[[str], bytes | bytearray | memoryview | None] = lambda _path: None,
        decode_validator: Callable[[bytes, str], bool] | None = None,
        corrupt_subject_ids: Iterable[str] = (),
        stale_policy_subject_ids: Iterable[str] = (),
        revalidate_subject_ids: Iterable[str] = (),
        intentionally_text_only_subject_ids: Iterable[str] = (),
        evaluation_support_bytes: bytes | bytearray | memoryview | None = None,
    ) -> AbbyVoiceDatasetManagerResult:
        source_rows = tuple(
            sorted(
                sources,
                key=lambda item: (
                    item.snapshot.logical_source,
                    item.snapshot.expected_sha256,
                ),
            )
        )
        if not source_rows:
            raise ValueError("at least one pinned voice source is required")
        source_identity = {
            "inventory_sha256": inventory.inventory_sha256,
            "snapshots": [item.snapshot.to_dict() for item in source_rows],
        }
        source_identity_bytes = _canonical_bytes(source_identity)
        source_manifest_id = (
            "abby-voice-source-set:sha256:"
            + sha256(source_identity_bytes).hexdigest()
        )
        normalization = self.normalizer.normalize_sources(
            (
                (
                    item.payload,
                    item.snapshot.logical_source,
                    item.snapshot.expected_sha256,
                    None,
                )
                for item in source_rows
            )
        )
        normalized_bundle = validate_bundle(
            responses=normalization.responses,
            templates=normalization.templates,
            audio=normalization.audio,
            provenance=normalization.provenance,
        )
        legacy = reconcile_legacy_audio_candidates(
            subjects=(*normalized_bundle.responses, *normalized_bundle.templates),
            candidates=legacy_candidates,
            inventory=inventory,
            byte_resolver=byte_resolver,
            decode_validator=decode_validator,
        )
        audio_by_id = {
            row.audio_id: row
            for row in (*normalized_bundle.audio, *legacy.linked_audio)
        }
        linked_by_response: dict[str, set[str]] = {}
        for row in legacy.linked_audio:
            if row.response_id:
                linked_by_response.setdefault(row.response_id, set()).add(row.audio_id)
        responses = tuple(
            replace(
                row,
                audio_ids=tuple(
                    sorted(set(row.audio_ids) | linked_by_response.get(row.response_id, set()))
                ),
            )
            for row in normalized_bundle.responses
        )
        bundle = validate_bundle(
            responses=responses,
            templates=normalized_bundle.templates,
            audio=audio_by_id.values(),
            provenance=normalized_bundle.provenance,
        )
        index = self.index_factory(
            templates=bundle.templates,
            responses=bundle.responses,
            audio=bundle.audio,
            provenance=bundle.provenance,
        )
        workset = VoiceAudioWorkset.build(
            responses=bundle.responses,
            templates=bundle.templates,
            audio=bundle.audio,
            source_manifest_id=source_manifest_id,
            policy_id=self.policy_id,
            corrupt_subject_ids=corrupt_subject_ids,
            stale_policy_subject_ids=stale_policy_subject_ids,
            revalidate_subject_ids=revalidate_subject_ids,
            intentionally_text_only_subject_ids=intentionally_text_only_subject_ids,
        )
        dispositions = self._dispositions(normalization, legacy)
        payloads = self._artifact_payloads(
            bundle=bundle,
            index=index,
            normalization=normalization,
            dispositions=dispositions,
            workset=workset,
            evaluation_support_bytes=(
                bytes(evaluation_support_bytes)
                if evaluation_support_bytes is not None
                else None
            ),
        )
        manifest, evaluation_artifact = self._artifact_manifest(
            payloads=payloads,
            source_identity_bytes=source_identity_bytes,
            source_manifest_id=source_manifest_id,
            evaluation_included=evaluation_support_bytes is not None,
        )
        return AbbyVoiceDatasetManagerResult(
            normalization=normalization,
            bundle=bundle,
            graphrag_index=index,
            legacy_reconciliation=legacy,
            workset=workset,
            dispositions=dispositions,
            artifact_manifest=manifest,
            artifact_payloads=payloads,
            source_manifest_id=source_manifest_id,
            evaluation_support_artifact=evaluation_artifact,
        )

    @staticmethod
    def _dispositions(
        normalization: NormalizationResult,
        legacy: LegacyAudioReconciliation,
    ) -> tuple[DatasetDisposition, ...]:
        values: dict[str, DatasetDisposition] = {}
        quarantined = {item.source_ref: item for item in normalization.quarantine}
        warnings = {item.source_ref: item for item in normalization.warnings}
        duplicate_refs = {
            ref
            for entry in normalization.duplicates
            for ref in entry.duplicate_source_refs
        }
        for item in normalization.provenance:
            if item.source_uri:
                values[item.source_uri] = DatasetDisposition(
                    item.source_uri,
                    item.source_sha256 or sha256(item.source_uri.encode()).hexdigest(),
                    "accepted",
                    "canonical_normalization",
                )
        for ref in duplicate_refs:
            warning = warnings.get(ref)
            values[ref] = DatasetDisposition(
                ref,
                warning.source_sha256 if warning else sha256(ref.encode()).hexdigest(),
                "quarantined",
                "duplicate_text",
            )
        for ref, item in quarantined.items():
            values[ref] = DatasetDisposition(
                ref, item.source_sha256, "quarantined", ",".join(item.reason_codes)
            )
        for item in legacy.dispositions:
            values[item.source_ref] = DatasetDisposition(
                item.source_ref,
                item.source_sha256,
                item.status.value,
                item.reason.value,
            )
        return tuple(sorted(values.values(), key=lambda item: item.source_ref))

    @staticmethod
    def _artifact_payloads(
        *,
        bundle: AbbyVoiceDatasetBundle,
        index: SlottedResponseIndex,
        normalization: NormalizationResult,
        dispositions: tuple[DatasetDisposition, ...],
        workset: VoiceAudioWorkset,
        evaluation_support_bytes: bytes | None,
    ) -> dict[str, bytes]:
        payloads = {
            "normalized/responses.jsonl": _jsonl(row.to_dict() for row in bundle.responses),
            "normalized/templates.jsonl": _jsonl(row.to_dict() for row in bundle.templates),
            "normalized/audio.jsonl": _jsonl(row.to_dict() for row in bundle.audio),
            "normalized/provenance.jsonl": _jsonl(row.to_dict() for row in bundle.provenance),
            "normalized/quarantine.jsonl": _jsonl(item.to_dict() for item in normalization.quarantine),
            "normalized/disposition.jsonl": _jsonl(item.to_dict() for item in dispositions),
            "normalized/audio-workset.jsonl": workset.canonical_bytes() + b"\n",
            "normalized/tts-work-manifest.json": workset.tts_manifest.canonical_bytes(),
            "normalized/asr-work-manifest.json": workset.asr_manifest.canonical_bytes(),
            "normalized/audio-validation-work-manifest.json": workset.validation_manifest.canonical_bytes(),
            "normalized/graphrag-index.json": _canonical_bytes(index.to_dict()),
            "normalized/quality-report.json": _canonical_bytes(normalization.quality_summary()),
        }
        if evaluation_support_bytes is not None:
            payloads["normalized/evaluation-support.jsonl"] = evaluation_support_bytes
        return payloads

    def _artifact_manifest(
        self,
        *,
        payloads: Mapping[str, bytes],
        source_identity_bytes: bytes,
        source_manifest_id: str,
        evaluation_included: bool,
    ) -> tuple[ArtifactManifest, Artifact | None]:
        producer = ProducerBinding(
            producer_id="producer:abby-voice-dataset-manager",
            name="AbbyVoiceDatasetManager",
            version=ABBY_VOICE_DATASET_MANAGER_VERSION,
            repository_revision=self.repository_commit,
        )
        config_bytes = _canonical_bytes(
            {"normalization": self.normalizer.config.to_dict(), "policy_id": self.policy_id}
        )
        config = ConfigBinding(
            config_id="config:abby-voice-dataset-manager",
            content_sha256=sha256(config_bytes).hexdigest(),
            schema_id="abby.voice.dataset-manager-config",
        )
        source_artifact = Artifact(
            artifact_id="artifact:" + source_manifest_id,
            role=ArtifactRole.PARENT,
            content_sha256=sha256(source_identity_bytes).hexdigest(),
            size=len(source_identity_bytes),
            metadata={"source_manifest_id": source_manifest_id},
        )
        artifacts: list[Artifact] = [source_artifact]
        evaluation_artifact: Artifact | None = None
        schema_by_path = {
            "normalized/responses.jsonl": ABBY_VOICE_RESPONSE_V2,
            "normalized/templates.jsonl": ABBY_VOICE_TEMPLATE_V2,
            "normalized/audio.jsonl": ABBY_VOICE_AUDIO_V2,
            "normalized/provenance.jsonl": ABBY_VOICE_PROVENANCE_V2,
            "normalized/evaluation-support.jsonl": ABBY_VOICE_EVALUATION_PENDING_SCHEMA,
        }
        for path, payload in sorted(payloads.items()):
            digest = sha256(payload).hexdigest()
            path_identity = sha256(path.encode("utf-8")).hexdigest()[:16]
            artifact = Artifact(
                artifact_id=f"artifact:abby-voice:{path_identity}:{digest}",
                role=ArtifactRole.OUTPUT,
                content_sha256=digest,
                size=len(payload),
                path=path,
                media_type="application/x-ndjson" if path.endswith(".jsonl") else "application/json",
                schema_id="abby.voice.artifact",
                schema_version=schema_by_path.get(path, "v1"),
                producer_id=producer.producer_id,
                config_id=config.config_id,
                parent_artifact_ids=(source_artifact.artifact_id,),
                review_status=(
                    "support_pending_g018"
                    if path == "normalized/evaluation-support.jsonl"
                    else "machine_checked"
                ),
            )
            artifacts.append(artifact)
            if path == "normalized/evaluation-support.jsonl":
                evaluation_artifact = artifact
        manifest = ArtifactManifest(
            artifacts=tuple(artifacts),
            repository_commit=self.repository_commit,
            producers=(producer,),
            configs=(config,),
            schema_versions={
                "audio": ABBY_VOICE_AUDIO_V2,
                "provenance": ABBY_VOICE_PROVENANCE_V2,
                "response": ABBY_VOICE_RESPONSE_V2,
                "template": ABBY_VOICE_TEMPLATE_V2,
            },
            tool_versions={"abby-voice-dataset-manager": ABBY_VOICE_DATASET_MANAGER_VERSION},
            deterministic_metadata={
                "evaluation_support": {
                    "included": evaluation_included,
                    "status": "pending_abby_voice_evaluation_v2",
                },
                "policy_id": self.policy_id,
                "source_manifest_id": source_manifest_id,
            },
        )
        return manifest, evaluation_artifact


__all__ = [
    "AbbyVoiceDatasetManager",
    "AbbyVoiceDatasetManagerResult",
    "DatasetDisposition",
    "PinnedVoiceSource",
]

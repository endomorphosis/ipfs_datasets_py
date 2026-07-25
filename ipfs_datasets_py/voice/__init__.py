"""Canonical Abby voice dataset contracts.

The package is intentionally dependency-light.  Arrow and Hugging Face
integrations are imported lazily by :mod:`ipfs_datasets_py.voice.schema`.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final

from .graphrag import (
    GRAPHRAG_INDEX_SCHEMA_VERSION,
    EvidenceRecord,
    GraphEdge,
    GraphNode,
    GraphRAGIngestionError,
    GraphRAGVoiceTemplateProvider,
    IngestionReceipt,
    SlottedResponseIndex,
    TemplateGraphSnapshot,
    TemplateMatch,
    UnsafeSlotBindingError,
)
from .normalize import (
    AbbyVoiceDatasetNormalizer,
    DuplicateLedgerEntry,
    NormalizationConfig,
    NormalizationResult,
    NormalizedInputDisposition,
    QualityIssue,
    QuarantineReason,
    QuarantineRecord,
    build_slotted_response_dag,
    deduplicate_voice_response_chunks,
    deterministic_split,
    normalize_indextts_spoken_text,
    normalize_manifest,
    normalize_spoken_text,
)
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceSchemaError,
    AbbyVoiceTemplate,
    get_arrow_schema,
    get_huggingface_features,
    get_pyarrow_schema,
    migrate_v1_record,
    parse_abby_voice_record,
    schema_columns,
    validate_abby_voice_bundle,
    validate_abby_voice_record,
    validate_bundle,
    validate_publishable,
    validate_rows,
)

if TYPE_CHECKING:
    from .dataset_manager import (
        AbbyVoiceDatasetManager,
        AbbyVoiceDatasetManagerResult,
        DatasetDisposition,
        PinnedVoiceSource,
    )
    from .legacy_sources import (
        LegacyAudioCandidate,
        LegacyAudioDisposition,
        LegacyAudioReconciliation,
        LegacyDispositionReason,
        LegacyDispositionStatus,
        reconcile_legacy_audio_candidates,
    )
    from .workset import (
        AudioArtifactDescriptor,
        AudioWorkItem,
        AudioWorkManifest,
        AudioWorkOperation,
        AudioWorkReason,
        VoiceAudioWorkset,
    )


_LAZY_EXPORTS: Final[dict[str, str]] = {
    "AbbyVoiceDatasetManager": ".dataset_manager",
    "AbbyVoiceDatasetManagerResult": ".dataset_manager",
    "DatasetDisposition": ".dataset_manager",
    "PinnedVoiceSource": ".dataset_manager",
    "LegacyAudioCandidate": ".legacy_sources",
    "LegacyAudioDisposition": ".legacy_sources",
    "LegacyAudioReconciliation": ".legacy_sources",
    "LegacyDispositionReason": ".legacy_sources",
    "LegacyDispositionStatus": ".legacy_sources",
    "reconcile_legacy_audio_candidates": ".legacy_sources",
    "AudioArtifactDescriptor": ".workset",
    "AudioWorkItem": ".workset",
    "AudioWorkManifest": ".workset",
    "AudioWorkOperation": ".workset",
    "AudioWorkReason": ".workset",
    "VoiceAudioWorkset": ".workset",
}


def __getattr__(name: str) -> Any:
    """Load data-manager contracts only when callers request them."""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))

__all__ = [
    "ABBY_VOICE_AUDIO_V2",
    "ABBY_VOICE_PROVENANCE_V2",
    "ABBY_VOICE_RESPONSE_V2",
    "ABBY_VOICE_TEMPLATE_V2",
    "AbbyVoiceAudio",
    "AbbyVoiceProvenance",
    "AbbyVoiceResponse",
    "AbbyVoiceSchemaError",
    "AbbyVoiceTemplate",
    "AbbyVoiceDatasetNormalizer",
    "DuplicateLedgerEntry",
    "NormalizationConfig",
    "NormalizedInputDisposition",
    "NormalizationResult",
    "QualityIssue",
    "QuarantineReason",
    "QuarantineRecord",
    "GRAPHRAG_INDEX_SCHEMA_VERSION",
    "EvidenceRecord",
    "GraphEdge",
    "GraphNode",
    "GraphRAGIngestionError",
    "GraphRAGVoiceTemplateProvider",
    "IngestionReceipt",
    "SlottedResponseIndex",
    "TemplateGraphSnapshot",
    "TemplateMatch",
    "UnsafeSlotBindingError",
    "AbbyVoiceDatasetManager",
    "AbbyVoiceDatasetManagerResult",
    "DatasetDisposition",
    "PinnedVoiceSource",
    "LegacyAudioCandidate",
    "LegacyAudioDisposition",
    "LegacyAudioReconciliation",
    "LegacyDispositionReason",
    "LegacyDispositionStatus",
    "reconcile_legacy_audio_candidates",
    "AudioArtifactDescriptor",
    "AudioWorkItem",
    "AudioWorkManifest",
    "AudioWorkOperation",
    "AudioWorkReason",
    "VoiceAudioWorkset",
    "build_slotted_response_dag",
    "deduplicate_voice_response_chunks",
    "deterministic_split",
    "get_arrow_schema",
    "get_huggingface_features",
    "get_pyarrow_schema",
    "migrate_v1_record",
    "normalize_indextts_spoken_text",
    "normalize_manifest",
    "normalize_spoken_text",
    "parse_abby_voice_record",
    "schema_columns",
    "validate_abby_voice_bundle",
    "validate_abby_voice_record",
    "validate_bundle",
    "validate_publishable",
    "validate_rows",
]

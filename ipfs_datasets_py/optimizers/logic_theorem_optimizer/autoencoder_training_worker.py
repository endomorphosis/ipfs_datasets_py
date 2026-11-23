"""Independent, bounded projection jobs over immutable JSON checkpoints.

This is a worker boundary, not a scheduler or promotion authority. Each process
owns a private model. It emits an immutable candidate and evidence into a new
directory; it never opens a control database. Candidates default to full JSON;
opt-in sparse manifests reference explicitly supplied immutable dependencies.
"""

from __future__ import annotations

from .autoencoder_native_pool import worker_runtime
from .modal_autoencoder_adaptive_optimizer import normalize_projection_candidate_update_order

import gc
import hashlib
import inspect
import json
import math
import multiprocessing
import os
import platform
import re
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


SCHEMA_VERSION = "autoencoder-training-job-v4"
INDEXED_SCHEMA_VERSION = "autoencoder-training-job-v5"
PRODUCED_SCHEMA_VERSION = "autoencoder-training-job-v6"
ARROW_INPUT_SCHEMA_VERSION = "autoencoder-training-job-v7"
CAMPAIGN_SCHEMA_VERSION = "autoencoder-training-job-v8"
SPARSE_SCHEMA_VERSION = "autoencoder-training-job-v3"
PREVIOUS_SCHEMA_VERSION = "autoencoder-training-job-v2"
LEGACY_SCHEMA_VERSION = "autoencoder-training-job-v1"
MAX_BASE_DEPENDENCIES = 256
DEFAULT_TARGET_SHARD_MAX_BYTES = 64 * 1024 * 1024
MAX_TARGET_SHARD_BYTES = 256 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024
MAX_BASE_DEPENDENCY_BYTES = 4 * 1024 * 1024 * 1024
MAX_CORPUS_SOURCES = 256
MAX_CORPUS_SOURCE_BYTES = 256 * 1024 * 1024
MAX_CORPUS_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_CORPUS_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_CORPUS_INDEX_BYTES = 64 * 1024 * 1024
MAX_EMBEDDING_PRODUCTION_BYTES = 64 * 1024 * 1024
MAX_ARROW_EMBEDDING_INPUT_BYTES = 4 * 1024 * 1024
MAX_CAMPAIGN_METADATA_BYTES = 64 * 1024 * 1024
MAX_PRODUCED_RECORD_PROJECTION_BYTES = 4 * 1024 * 1024
MAX_CAMPAIGN_RECEIPTS = 256
MAX_CAMPAIGN_RECEIPT_BYTES = 64 * 1024 * 1024
MAX_CAMPAIGN_SOURCE_BYTES = 64 * 1024 * 1024
CAMPAIGN_ARTIFACT_FIELDS = ("source_inventory_artifact", "source_partitions_artifact",
    "embedding_receipt_set_artifact", "produced_record_projection_artifact")
CAMPAIGN_JOB_FIELDS = (*CAMPAIGN_ARTIFACT_FIELDS, "embedding_receipt_artifacts")
# An eligibility bound on encoded target volume, not a process RSS limit.
MAX_GC_DEFERRED_TARGET_BYTES = 256 * 1024 * 1024
BRIDGE_NAMES = (
    "modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router",
)
_JOB_LOCK = threading.Lock()
SOURCE_MODULE_NAMES = frozenset({"compiler", "decompiler", "parser", "autoencoder", "samples", "worker"})
_PROCESS_SOURCE_HASHES: dict[str, str] | None = None


class TrainingJobValidationError(ValueError):
    """A job cannot be executed with its declared identities or constraints."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: Any, allowed: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingJobValidationError(f"{name} must be an object")
    extra = set(value) - allowed
    if extra:
        raise TrainingJobValidationError(f"unknown {name} fields: {sorted(extra)}")
    return dict(value)


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise TrainingJobValidationError(f"{name} must be a string" + ("" if empty else " and nonempty"))
    return value


def _number(value: Any, name: str, minimum: float = 0, *, integer: bool = False) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrainingJobValidationError(f"{name} must be numeric")
    if not math.isfinite(value) or value < minimum or (integer and not isinstance(value, int)):
        raise TrainingJobValidationError(f"{name} must be finite and >= {minimum}" + (" (integer)" if integer else ""))
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise TrainingJobValidationError("configuration numbers must be finite")
        return value
    raise TrainingJobValidationError("configuration must contain JSON values")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _parse_json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TrainingJobValidationError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise TrainingJobValidationError(f"nonfinite JSON value: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


@dataclass(frozen=True)
class CheckpointArtifact:
    path: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        _text(self.path, "base_checkpoint.path")
        if not Path(self.path).is_absolute():
            raise TrainingJobValidationError("base_checkpoint.path must be absolute")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise TrainingJobValidationError("base_checkpoint.sha256 must be a lowercase SHA-256")
        _number(self.bytes, "base_checkpoint.bytes", 1, integer=True)

    @classmethod
    def from_dict(cls, value: Any) -> "CheckpointArtifact":
        return cls(**_object(value, {field.name for field in fields(cls)}, "base_checkpoint"))


@dataclass(frozen=True)
class ModelVariant:
    source_language: str = "en"
    target_formal_language: str = "typed_deontic_ir"
    jurisdiction: str = "us"
    model_variant: str = "modal_autoencoder"

    def __post_init__(self) -> None:
        for field in fields(self):
            _text(getattr(self, field.name), f"variant.{field.name}")
        if self.source_language != "en":
            raise TrainingJobValidationError("only the English source frontend is qualified")
        if self.target_formal_language != "typed_deontic_ir" or self.jurisdiction != "us":
            raise TrainingJobValidationError("this worker supports typed_deontic_ir with the us_code sample frontend")

    @classmethod
    def from_dict(cls, value: Any) -> "ModelVariant":
        return cls(**_object(value, {field.name for field in fields(cls)}, "variant"))


@dataclass(frozen=True)
class SampleRecord:
    title: str
    section: str
    text: str
    citation: str | None = None
    embedding_model: str = "mock:stable-sha256"
    embedding_vector: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        for name in ("title", "section", "text", "embedding_model"):
            _text(getattr(self, name), f"sample.{name}")
        if self.citation is not None:
            _text(self.citation, "sample.citation")
        if self.embedding_vector is not None:
            if not isinstance(self.embedding_vector, (list, tuple)) or not self.embedding_vector:
                raise TrainingJobValidationError("sample.embedding_vector must be a nonempty array")
            for value in self.embedding_vector:
                _number(value, "sample.embedding_vector", -float("inf"))
            object.__setattr__(self, "embedding_vector", tuple(self.embedding_vector))
        elif self.embedding_model != "mock:stable-sha256":
            raise TrainingJobValidationError("external embedding models require supplied vectors; workers do not download weights")

    @classmethod
    def from_dict(cls, value: Any) -> "SampleRecord":
        return cls(**_object(value, {field.name for field in fields(cls)}, "sample"))


@dataclass(frozen=True)
class TrainingConfig:
    legal_ir_bridge_names: tuple[str, ...] = BRIDGE_NAMES
    legal_ir_evaluate_provers: bool = False
    legal_ir_parallel_workers: int = 1
    metric_disk_cache: int = 0
    use_sample_memory: bool = False
    epochs: int = 1
    max_seconds: float = 180.0
    max_line_search_attempts: int = 1
    projection_max_update_families: int = 1
    projection_update_backend: str = "python_sparse_batch"
    learning_rate: float = 0.35
    l2_regularization: float = 0.0
    max_cosine_regression: float = 0.01
    max_reconstruction_regression: float = 0.02
    max_cross_entropy_regression: float = 0.0
    max_legal_ir_loss_regression: float = 0.02
    objective_cross_entropy_weight: float = 1.0
    objective_reconstruction_weight: float = 1.0
    objective_cosine_gap_weight: float = 1.5
    objective_legal_ir_weight: float = 1.0
    hard_example_fraction: float = 1.0
    profile_projection: bool = False
    projection_max_composed_refinement_attempts: int = 0
    projection_optimizer_mode: str = "fixed"
    projection_momentum: float = 0.0
    projection_candidate_update_order: tuple[str, ...] | None = None
    projection_reconstruction_objective: str = "safety_projected"

    def __post_init__(self) -> None:
        try:
            order = normalize_projection_candidate_update_order(self.projection_candidate_update_order)
        except ValueError as exc:
            raise TrainingJobValidationError(str(exc)) from exc
        object.__setattr__(self, "projection_candidate_update_order", order)
        if (type(self.projection_reconstruction_objective) is not str
                or self.projection_reconstruction_objective not in {"safety_projected", "raw_decoder"}):
            raise TrainingJobValidationError("projection_reconstruction_objective must be safety_projected or raw_decoder")
        if not isinstance(self.legal_ir_bridge_names, (list, tuple)):
            raise TrainingJobValidationError("legal_ir_bridge_names must be an array")
        names = tuple(self.legal_ir_bridge_names)
        if not names or any(not isinstance(name, str) or name not in BRIDGE_NAMES for name in names) or len(set(names)) != len(names):
            raise TrainingJobValidationError("bridge names must be a nonempty unique subset of the five qualified bridges")
        object.__setattr__(self, "legal_ir_bridge_names", names)
        if self.legal_ir_evaluate_provers is not False or self.use_sample_memory is not False:
            raise TrainingJobValidationError("this worker requires provers=False and use_sample_memory=False")
        if type(self.metric_disk_cache) is not int or self.metric_disk_cache != 0:
            raise TrainingJobValidationError("this worker requires a cold metric disk cache (0)")
        if self.projection_update_backend != "python_sparse_batch":
            raise TrainingJobValidationError("this worker requires the profiled python_sparse_batch backend")
        if type(self.profile_projection) is not bool:
            raise TrainingJobValidationError("profile_projection must be boolean")
        if (type(self.projection_max_composed_refinement_attempts) is not int
                or not 0 <= self.projection_max_composed_refinement_attempts <= 3):
            raise TrainingJobValidationError("projection_max_composed_refinement_attempts must be 0..3")
        integers = {"legal_ir_parallel_workers", "epochs", "max_line_search_attempts", "projection_max_update_families"}
        for name in integers:
            _number(getattr(self, name), name, 1, integer=True)
        for name in ("max_seconds", "learning_rate", "hard_example_fraction"):
            _number(getattr(self, name), name)
            if getattr(self, name) <= 0:
                raise TrainingJobValidationError(f"{name} must be positive")
        if self.hard_example_fraction > 1:
            raise TrainingJobValidationError("hard_example_fraction must be <= 1")
        for name in ("l2_regularization", "max_cosine_regression", "max_reconstruction_regression",
                     "max_cross_entropy_regression", "max_legal_ir_loss_regression",
                     "objective_cross_entropy_weight", "objective_reconstruction_weight",
                     "objective_cosine_gap_weight", "objective_legal_ir_weight"):
            _number(getattr(self, name), name)
        if self.projection_max_composed_refinement_attempts and self.l2_regularization != 0.0:
            raise TrainingJobValidationError("composed refinement currently requires zero l2_regularization")
        if (self.projection_candidate_update_order and set(self.projection_candidate_update_order) & {"decoded_embedding_nonview", "decoded_embedding_structural"}
                and self.l2_regularization != 0.0):
            raise TrainingJobValidationError("support-preserving embedding operators require zero l2_regularization to preserve untouched view heads")
        if (type(self.projection_optimizer_mode) is not str
                or self.projection_optimizer_mode not in {"fixed", "guarded_adaptive", "productive_adaptive"}):
            raise TrainingJobValidationError("projection_optimizer_mode must be fixed, guarded_adaptive or productive_adaptive")
        _number(self.projection_momentum, "projection_momentum")
        if self.projection_momentum > 0.9:
            raise TrainingJobValidationError("projection_momentum must be within 0..0.9")
        if self.projection_momentum and (self.projection_optimizer_mode not in {"guarded_adaptive", "productive_adaptive"}
                                         or self.max_line_search_attempts < 2):
            raise TrainingJobValidationError("projection_momentum requires guarded_adaptive or productive_adaptive and at least two line search attempts")
        if self.projection_optimizer_mode == "productive_adaptive" and self.max_line_search_attempts < 2:
            raise TrainingJobValidationError("productive_adaptive requires at least two line search attempts")
        if self.projection_optimizer_mode in {"guarded_adaptive", "productive_adaptive"}:
            if self.l2_regularization != 0.0:
                raise TrainingJobValidationError(f"{self.projection_optimizer_mode} currently requires zero l2_regularization")
            if self.epochs > 32 or self.max_line_search_attempts > 10 or self.learning_rate > 1:
                raise TrainingJobValidationError(f"{self.projection_optimizer_mode} requires epochs <= 32, attempts <= 10 and learning_rate <= 1")
            if self.max_seconds > 300:
                raise TrainingJobValidationError(f"{self.projection_optimizer_mode} requires max_seconds <= 300")

    def projection_kwargs(self) -> dict[str, Any]:
        return {key: value for key, value in self.to_dict().items()
                if key not in {"metric_disk_cache", "use_sample_memory", "profile_projection"}}

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Preserve archived job and training-policy identities when this new
        # opt-in is disabled. Enabled budgets must be bound into both.
        if self.projection_candidate_update_order is None:
            result.pop("projection_candidate_update_order")
        if self.projection_reconstruction_objective == "safety_projected":
            result.pop("projection_reconstruction_objective")
        if self.projection_max_composed_refinement_attempts == 0:
            result.pop("projection_max_composed_refinement_attempts")
        if self.projection_optimizer_mode == "fixed" and self.projection_momentum == 0.0:
            result.pop("projection_optimizer_mode")
            result.pop("projection_momentum")
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "TrainingConfig":
        return cls(**_object(value, {field.name for field in fields(cls)}, "training_config"))


@dataclass(frozen=True)
class TrainingJobSpec:
    job_id: str
    run_id: str
    base_version_id: str
    base_checkpoint: CheckpointArtifact
    output_directory: str
    code_identity: str
    dataset_snapshot_id: str
    split_snapshot_id: str
    samples: tuple[SampleRecord, ...]
    validation_samples: tuple[SampleRecord, ...] = ()
    variant: ModelVariant = ModelVariant()
    training_config: TrainingConfig = TrainingConfig()
    autoencoder_config: Mapping[str, Any] | None = None
    expected_source_sha256: Mapping[str, str] | None = None
    target_snapshot_id: str = ""
    target_snapshot_artifact: CheckpointArtifact | None = None
    capture_sparse_patches: bool = False
    arrow_feature_weights_artifact: CheckpointArtifact | None = None
    candidate_storage: str = "full"
    base_checkpoint_dependencies: tuple[CheckpointArtifact, ...] = ()
    corpus_manifest_artifact: CheckpointArtifact | None = None
    corpus_source_artifacts: tuple[CheckpointArtifact, ...] = ()
    corpus_index_artifact: CheckpointArtifact | None = None
    corpus_selection_sha256: str = ""
    schema_version: str = SCHEMA_VERSION
    embedding_production_artifact: CheckpointArtifact | None = None
    arrow_embedding_inputs_artifact: CheckpointArtifact | None = None
    source_inventory_artifact: CheckpointArtifact | None = None
    source_partitions_artifact: CheckpointArtifact | None = None
    embedding_receipt_set_artifact: CheckpointArtifact | None = None
    produced_record_projection_artifact: CheckpointArtifact | None = None
    embedding_receipt_artifacts: tuple[CheckpointArtifact, ...] = ()
    target_shard_max_bytes: int = DEFAULT_TARGET_SHARD_MAX_BYTES

    def __post_init__(self) -> None:
        for name in ("job_id", "run_id", "base_version_id", "output_directory", "code_identity",
                     "dataset_snapshot_id", "split_snapshot_id"):
            _text(getattr(self, name), name)
        _text(self.target_snapshot_id, "target_snapshot_id", empty=True)
        if bool(self.target_snapshot_id) != (self.target_snapshot_artifact is not None):
            raise TrainingJobValidationError("target snapshot ID and artifact must be supplied together")
        if self.target_snapshot_artifact is not None and not isinstance(self.target_snapshot_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("target_snapshot_artifact must be CheckpointArtifact")
        if type(self.target_shard_max_bytes) is not int or not 1 <= self.target_shard_max_bytes <= MAX_TARGET_SHARD_BYTES:
            raise TrainingJobValidationError("target_shard_max_bytes must be a positive integer <= 256 MiB")
        if self.target_shard_max_bytes != DEFAULT_TARGET_SHARD_MAX_BYTES and self.target_snapshot_artifact is None:
            raise TrainingJobValidationError("nondefault target_shard_max_bytes requires a target snapshot artifact")
        if type(self.capture_sparse_patches) is not bool:
            raise TrainingJobValidationError("capture_sparse_patches must be boolean")
        if self.arrow_feature_weights_artifact is not None and not isinstance(self.arrow_feature_weights_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("arrow_feature_weights_artifact must be CheckpointArtifact")
        if self.schema_version not in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION, SPARSE_SCHEMA_VERSION, PREVIOUS_SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}:
            raise TrainingJobValidationError("unsupported training job schema")
        if self.candidate_storage not in {"full", "sparse"}:
            raise TrainingJobValidationError("candidate_storage must be full or sparse")
        if self.candidate_storage == "sparse" and not self.capture_sparse_patches:
            raise TrainingJobValidationError("sparse candidate storage requires capture_sparse_patches")
        dependencies = self.base_checkpoint_dependencies
        if not isinstance(dependencies, (list, tuple)) or any(not isinstance(item, CheckpointArtifact) for item in dependencies):
            raise TrainingJobValidationError("base_checkpoint_dependencies must contain CheckpointArtifact values")
        if len(dependencies) > MAX_BASE_DEPENDENCIES:
            raise TrainingJobValidationError("base checkpoint dependency count exceeds worker bound")
        object.__setattr__(self, "base_checkpoint_dependencies", tuple(dependencies))
        if self.schema_version not in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION, SPARSE_SCHEMA_VERSION} and (self.candidate_storage != "full" or dependencies):
            raise TrainingJobValidationError("sparse checkpoints and base dependencies require the v3 job schema")
        if self.schema_version == LEGACY_SCHEMA_VERSION and (
            self.target_snapshot_artifact is not None or self.capture_sparse_patches or self.arrow_feature_weights_artifact is not None
        ):
            raise TrainingJobValidationError("shared artifacts and sparse capture require the v2 job schema")
        if not Path(self.output_directory).is_absolute():
            raise TrainingJobValidationError("output_directory must be absolute")
        for value, cls, name in ((self.base_checkpoint, CheckpointArtifact, "base_checkpoint"),
                                 (self.variant, ModelVariant, "variant"),
                                 (self.training_config, TrainingConfig, "training_config")):
            if not isinstance(value, cls):
                raise TrainingJobValidationError(f"{name} must be {cls.__name__}")
        if self.schema_version in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION, SPARSE_SCHEMA_VERSION}:
            artifacts = (self.base_checkpoint, *dependencies)
            if any(item.bytes > MAX_CHECKPOINT_BYTES for item in artifacts):
                raise TrainingJobValidationError("base checkpoint artifact exceeds worker byte bound")
            if sum(item.bytes for item in artifacts) > MAX_BASE_DEPENDENCY_BYTES:
                raise TrainingJobValidationError("base checkpoint dependencies exceed aggregate worker byte bound")
            if len({item.sha256 for item in artifacts}) != len(artifacts):
                raise TrainingJobValidationError("duplicate base checkpoint dependency SHA-256")
        corpus_sources = self.corpus_source_artifacts
        if not isinstance(corpus_sources, (tuple, list)) or any(not isinstance(item, CheckpointArtifact) for item in corpus_sources):
            raise TrainingJobValidationError("corpus_source_artifacts must contain CheckpointArtifact values")
        object.__setattr__(self, "corpus_source_artifacts", tuple(corpus_sources))
        if self.corpus_manifest_artifact is not None and not isinstance(self.corpus_manifest_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("corpus_manifest_artifact must be CheckpointArtifact")
        if bool(corpus_sources) != (self.corpus_manifest_artifact is not None):
            raise TrainingJobValidationError("corpus manifest and source artifacts must be supplied together")
        if self.schema_version not in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION} and self.corpus_manifest_artifact is not None:
            raise TrainingJobValidationError("corpus manifests require the v4 job schema")
        if (len(corpus_sources) > MAX_CORPUS_SOURCES
                or any(item.bytes > MAX_CORPUS_SOURCE_BYTES for item in corpus_sources)
                or sum(item.bytes for item in corpus_sources) > MAX_CORPUS_TOTAL_BYTES):
            raise TrainingJobValidationError("corpus sources exceed worker count or byte bounds")
        if len({item.sha256 for item in corpus_sources}) != len(corpus_sources):
            raise TrainingJobValidationError("duplicate corpus source SHA-256")
        if self.corpus_manifest_artifact is not None and self.corpus_manifest_artifact.bytes > MAX_CORPUS_MANIFEST_BYTES:
            raise TrainingJobValidationError("corpus manifest exceeds worker byte bound")
        if self.corpus_index_artifact is not None and not isinstance(self.corpus_index_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("corpus_index_artifact must be CheckpointArtifact")
        _text(self.corpus_selection_sha256, "corpus_selection_sha256", empty=True)
        if self.corpus_selection_sha256 and not re.fullmatch(r"[0-9a-f]{64}", self.corpus_selection_sha256):
            raise TrainingJobValidationError("corpus_selection_sha256 must be a lowercase SHA-256")
        if self.schema_version in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            if self.corpus_manifest_artifact is None or not corpus_sources or self.corpus_index_artifact is None or not self.corpus_selection_sha256:
                raise TrainingJobValidationError("v5 requires corpus manifest, source artifacts, frozen index and selection SHA-256")
        elif self.corpus_index_artifact is not None or self.corpus_selection_sha256:
            raise TrainingJobValidationError("frozen corpus index bindings require the v5 job schema")
        if self.corpus_index_artifact is not None and self.corpus_index_artifact.bytes > MAX_CORPUS_INDEX_BYTES:
            raise TrainingJobValidationError("corpus index exceeds worker byte bound")
        if self.embedding_production_artifact is not None and not isinstance(self.embedding_production_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("embedding_production_artifact must be CheckpointArtifact")
        if self.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            if self.embedding_production_artifact is None:
                raise TrainingJobValidationError("v6 requires embedding_production_artifact")
        elif self.embedding_production_artifact is not None:
            raise TrainingJobValidationError("embedding production bindings require the v6 job schema")
        if self.embedding_production_artifact is not None and self.embedding_production_artifact.bytes > MAX_EMBEDDING_PRODUCTION_BYTES:
            raise TrainingJobValidationError("embedding production receipt exceeds worker byte bound")
        if self.arrow_embedding_inputs_artifact is not None and not isinstance(self.arrow_embedding_inputs_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("arrow_embedding_inputs_artifact must be CheckpointArtifact")
        if self.schema_version == ARROW_INPUT_SCHEMA_VERSION:
            if self.arrow_embedding_inputs_artifact is None:
                raise TrainingJobValidationError("v7 requires arrow_embedding_inputs_artifact")
        elif self.arrow_embedding_inputs_artifact is not None:
            raise TrainingJobValidationError("Arrow embedding inputs require the v7 job schema")
        if self.arrow_embedding_inputs_artifact is not None and self.arrow_embedding_inputs_artifact.bytes > MAX_ARROW_EMBEDDING_INPUT_BYTES:
            raise TrainingJobValidationError("Arrow embedding inputs exceed worker byte bound")
        campaign_refs = tuple(getattr(self, name) for name in CAMPAIGN_ARTIFACT_FIELDS)
        if any(ref is not None and not isinstance(ref, CheckpointArtifact) for ref in campaign_refs):
            raise TrainingJobValidationError("campaign artifact fields must contain CheckpointArtifact values")
        receipt_refs = self.embedding_receipt_artifacts
        if not isinstance(receipt_refs, (tuple, list)) or any(not isinstance(ref, CheckpointArtifact) for ref in receipt_refs):
            raise TrainingJobValidationError("embedding_receipt_artifacts must contain CheckpointArtifact values")
        object.__setattr__(self, "embedding_receipt_artifacts", tuple(receipt_refs))
        if self.schema_version == CAMPAIGN_SCHEMA_VERSION:
            if any(ref is None for ref in campaign_refs) or not receipt_refs or self.corpus_manifest_artifact is None or not corpus_sources:
                raise TrainingJobValidationError("v8 requires all campaign artifacts, selected receipts, corpus manifest and source artifacts")
            if any(ref.bytes > MAX_CAMPAIGN_METADATA_BYTES for ref in campaign_refs[:3]):
                raise TrainingJobValidationError("campaign metadata exceeds worker byte bound")
            if self.produced_record_projection_artifact.bytes > MAX_PRODUCED_RECORD_PROJECTION_BYTES:
                raise TrainingJobValidationError("produced record projection exceeds worker byte bound")
            if (len(receipt_refs) > MAX_CAMPAIGN_RECEIPTS
                    or any(ref.bytes > MAX_CAMPAIGN_RECEIPT_BYTES for ref in receipt_refs)
                    or sum(ref.bytes for ref in receipt_refs) > MAX_CAMPAIGN_RECEIPT_BYTES):
                raise TrainingJobValidationError("selected campaign receipts exceed worker count or byte bound")
            if len({ref.sha256 for ref in receipt_refs}) != len(receipt_refs):
                raise TrainingJobValidationError("duplicate selected campaign receipt SHA-256")
            if sum(ref.bytes for ref in corpus_sources) > MAX_CAMPAIGN_SOURCE_BYTES:
                raise TrainingJobValidationError("selected campaign sources exceed worker byte bound")
        elif any(ref is not None for ref in campaign_refs) or receipt_refs:
            raise TrainingJobValidationError("campaign bindings require the v8 job schema")
        for name in ("samples", "validation_samples"):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or any(not isinstance(row, SampleRecord) for row in values):
                raise TrainingJobValidationError(f"{name} must contain SampleRecord values")
            object.__setattr__(self, name, tuple(values))
        if not self.samples:
            raise TrainingJobValidationError("samples must not be empty")
        if self.training_config.projection_reconstruction_objective == "raw_decoder":
            training_texts = {" ".join(row.text.casefold().split()) for row in self.samples}
            validation_texts = {" ".join(row.text.casefold().split()) for row in self.validation_samples}
            if not validation_texts or training_texts & validation_texts:
                raise TrainingJobValidationError("raw_decoder requires nonempty disjoint validation_samples")
        if self.training_config.projection_max_composed_refinement_attempts:
            training_texts = {" ".join(row.text.casefold().split()) for row in self.samples}
            validation_texts = {" ".join(row.text.casefold().split()) for row in self.validation_samples}
            if not validation_texts or training_texts & validation_texts:
                raise TrainingJobValidationError("composed refinement requires nonempty disjoint validation_samples")
        if self.training_config.projection_optimizer_mode in {"guarded_adaptive", "productive_adaptive"}:
            training_texts = {" ".join(row.text.casefold().split()) for row in self.samples}
            validation_texts = {" ".join(row.text.casefold().split()) for row in self.validation_samples}
            if not validation_texts or training_texts & validation_texts:
                raise TrainingJobValidationError(f"{self.training_config.projection_optimizer_mode} requires nonempty disjoint validation_samples")
        if self.schema_version in {CAMPAIGN_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION} and not self.validation_samples:
            # The native optimizer otherwise uses training rows for line search.
            # Indexed jobs must bind every validation row to the validation split.
            raise TrainingJobValidationError("v5 requires explicit nonempty validation_samples")
        if self.autoencoder_config is not None and not isinstance(self.autoencoder_config, Mapping):
            raise TrainingJobValidationError("autoencoder_config must be an object")
        object.__setattr__(self, "autoencoder_config", _freeze(self.autoencoder_config or {}))
        expected = self.expected_source_sha256
        if expected is not None:
            if not isinstance(expected, Mapping) or (expected and set(expected) != SOURCE_MODULE_NAMES):
                raise TrainingJobValidationError("expected_source_sha256 must name all six qualified source modules")
            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in expected.values()):
                raise TrainingJobValidationError("expected source hashes must be lowercase SHA-256 values")
        object.__setattr__(self, "expected_source_sha256", _freeze(expected or {}))

    @classmethod
    def from_dict(cls, value: Any) -> "TrainingJobSpec | ReviewedDecoderTrainingJobSpec":
        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA:
            return ReviewedDigestCacheEpochTrainingJobSpec.from_dict(value)
        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DIGEST_OMITTED_JOB_SCHEMA:
            return ReviewedDigestOmittedDecoderTrainingJobSpec.from_dict(value)
        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_MIXED_DECODER_SCHEMA_VERSION:
            return ReviewedMixedDecoderTrainingJobSpec.from_dict(value)
        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DECODER_SCHEMA_VERSION:
            return ReviewedDecoderTrainingJobSpec.from_dict(value)
        data = _object(value, {field.name for field in fields(cls)}, "job")
        # Previously schema-less JSON meant v2; do not silently change its
        # canonical identity when reading an archived job specification.
        data.setdefault("schema_version", PREVIOUS_SCHEMA_VERSION)
        if data["schema_version"] != CAMPAIGN_SCHEMA_VERSION and set(data).intersection(CAMPAIGN_JOB_FIELDS):
            raise TrainingJobValidationError("campaign fields require the v8 job schema, including explicit null fields")
        if data["schema_version"] == CAMPAIGN_SCHEMA_VERSION and set(data).intersection({
                "corpus_index_artifact", "corpus_selection_sha256", "embedding_production_artifact", "arrow_embedding_inputs_artifact"}):
            raise TrainingJobValidationError("v8 forbids legacy index, selection, single producer and Arrow input fields")
        for name in CAMPAIGN_ARTIFACT_FIELDS:
            if data.get(name) is not None:
                data[name] = CheckpointArtifact.from_dict(data[name])
        if "embedding_receipt_artifacts" in data:
            if not isinstance(data["embedding_receipt_artifacts"], (tuple, list)):
                raise TrainingJobValidationError("embedding_receipt_artifacts must be an array")
            data["embedding_receipt_artifacts"] = tuple(CheckpointArtifact.from_dict(item) for item in data["embedding_receipt_artifacts"])
        for name, factory in (("base_checkpoint", CheckpointArtifact), ("variant", ModelVariant),
                              ("training_config", TrainingConfig)):
            if name in data:
                data[name] = factory.from_dict(data[name])
        if data.get("target_snapshot_artifact") is not None:
            data["target_snapshot_artifact"] = CheckpointArtifact.from_dict(data["target_snapshot_artifact"])
        if data.get("arrow_feature_weights_artifact") is not None:
            data["arrow_feature_weights_artifact"] = CheckpointArtifact.from_dict(data["arrow_feature_weights_artifact"])
        if data.get("corpus_manifest_artifact") is not None:
            data["corpus_manifest_artifact"] = CheckpointArtifact.from_dict(data["corpus_manifest_artifact"])
        if data.get("corpus_index_artifact") is not None:
            data["corpus_index_artifact"] = CheckpointArtifact.from_dict(data["corpus_index_artifact"])
        if data.get("embedding_production_artifact") is not None:
            data["embedding_production_artifact"] = CheckpointArtifact.from_dict(data["embedding_production_artifact"])
        if data.get("arrow_embedding_inputs_artifact") is not None:
            data["arrow_embedding_inputs_artifact"] = CheckpointArtifact.from_dict(data["arrow_embedding_inputs_artifact"])
        if "corpus_source_artifacts" in data:
            if not isinstance(data["corpus_source_artifacts"], (tuple, list)):
                raise TrainingJobValidationError("corpus_source_artifacts must be an array")
            data["corpus_source_artifacts"] = tuple(CheckpointArtifact.from_dict(item) for item in data["corpus_source_artifacts"])
        if "base_checkpoint_dependencies" in data:
            if not isinstance(data["base_checkpoint_dependencies"], (tuple, list)):
                raise TrainingJobValidationError("base_checkpoint_dependencies must be an array")
            data["base_checkpoint_dependencies"] = tuple(
                CheckpointArtifact.from_dict(item) for item in data["base_checkpoint_dependencies"]
            )
        for name in ("samples", "validation_samples"):
            if name in data:
                if not isinstance(data[name], (tuple, list)):
                    raise TrainingJobValidationError(f"{name} must be an array")
                data[name] = tuple(SampleRecord.from_dict(row) for row in data[name])
        try:
            spec = cls(**data)
            # The earliest v1 receipts predate this optional field entirely.
            # Preserve omission when decoding those archived bytes; later v1
            # payloads with an explicit empty object keep that object.
            if data["schema_version"] == LEGACY_SCHEMA_VERSION and "expected_source_sha256" not in data:
                object.__setattr__(spec, "_legacy_omitted_source_manifest", True)
            return spec
        except TypeError as exc:
            raise TrainingJobValidationError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        for name in ("base_checkpoint", "variant", "training_config"):
            result[name] = asdict(result[name])
        result["training_config"] = self.training_config.to_dict()
        if self.target_snapshot_artifact is not None:
            result["target_snapshot_artifact"] = asdict(self.target_snapshot_artifact)
        if self.target_shard_max_bytes == DEFAULT_TARGET_SHARD_MAX_BYTES:
            result.pop("target_shard_max_bytes")
        if self.arrow_feature_weights_artifact is not None:
            result["arrow_feature_weights_artifact"] = asdict(self.arrow_feature_weights_artifact)
        result["base_checkpoint_dependencies"] = [asdict(item) for item in self.base_checkpoint_dependencies]
        result["corpus_manifest_artifact"] = asdict(self.corpus_manifest_artifact) if self.corpus_manifest_artifact else None
        result["corpus_source_artifacts"] = [asdict(item) for item in self.corpus_source_artifacts]
        result["corpus_index_artifact"] = asdict(self.corpus_index_artifact) if self.corpus_index_artifact else None
        result["embedding_production_artifact"] = asdict(self.embedding_production_artifact) if self.embedding_production_artifact else None
        result["arrow_embedding_inputs_artifact"] = asdict(self.arrow_embedding_inputs_artifact) if self.arrow_embedding_inputs_artifact else None
        for name in CAMPAIGN_ARTIFACT_FIELDS:
            ref = getattr(self, name)
            result[name] = asdict(ref) if ref else None
        result["embedding_receipt_artifacts"] = [asdict(ref) for ref in self.embedding_receipt_artifacts]
        for name in ("samples", "validation_samples"):
            result[name] = [asdict(row) for row in result[name]]
        for name in ("autoencoder_config", "expected_source_sha256"):
            result[name] = _thaw(getattr(self, name))
        if self.schema_version == LEGACY_SCHEMA_VERSION:
            for name in ("target_snapshot_artifact", "capture_sparse_patches", "arrow_feature_weights_artifact"):
                result.pop(name)
            if getattr(self, "_legacy_omitted_source_manifest", False):
                result.pop("expected_source_sha256")
        if self.schema_version not in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION, SPARSE_SCHEMA_VERSION}:
            for name in ("candidate_storage", "base_checkpoint_dependencies"):
                result.pop(name)
        if self.schema_version not in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION}:
            for name in ("corpus_manifest_artifact", "corpus_source_artifacts"):
                result.pop(name)
        if self.schema_version not in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            for name in ("corpus_index_artifact", "corpus_selection_sha256"):
                result.pop(name)
        if self.schema_version not in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            result.pop("embedding_production_artifact")
        if self.schema_version != ARROW_INPUT_SCHEMA_VERSION:
            result.pop("arrow_embedding_inputs_artifact")
        if self.schema_version != CAMPAIGN_SCHEMA_VERSION:
            for name in CAMPAIGN_JOB_FIELDS:
                result.pop(name)
        return _parse_json(_json_bytes(result))

    @property
    def canonical_sha256(self) -> str:
        return _digest(_json_bytes(self.to_dict()))

    def __reduce__(self):
        # MappingProxyType freezes configuration but is not itself picklable.
        # Reconstruct through validation when multiprocessing uses spawn.
        return (type(self).from_dict, (self.to_dict(),))


# This separate profile keeps the historical v1-v8 projection and checkpoint
# formats intact. Backend objects are trusted, caller-owned execution providers;
# selecting this schema is never resource admission or a model download.
REVIEWED_DECODER_SCHEMA_VERSION = "autoencoder-training-job-v9-reviewed-legal-ir"
REVIEWED_MIXED_DECODER_SCHEMA_VERSION = "autoencoder-training-job-v10-reviewed-mixed-legal-ir"
REVIEWED_DIGEST_OMITTED_JOB_SCHEMA = "reviewed-mixed-digest-omitted-decoder-job/v1"
REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA = "reviewed-digest-omitted-decoder-checkpoint/v1"
REVIEWED_DIGEST_OMITTED_WORKER_RECEIPT_SCHEMA = "reviewed-digest-omitted-decoder-worker-receipt/v1"
REVIEWED_DIGEST_OMITTED_TARGET_CODEC = "complete-reviewed-norm-digest-omitted-json/v1"
REVIEWED_DIGEST_OMITTED_CHATML_PROFILE = "qwen2-chatml-digest-omitted-legal-ir/v1"
REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA = "reviewed-decoder-digest-omitted-generation-policy/v1"
REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA = "reviewed-decoder-digest-omitted-terminal-generation-policy/v1"
REVIEWED_DECODER_CANONICAL_TERMINAL_PROFILE = "digest-omitted-canonical-body-eos/v1"
REVIEWED_DIGEST_OMITTED_RECIPE_SCHEMA = "reviewed-local-digest-omitted-decoder-recipe/v1"
REVIEWED_MIXED_ADMISSION_PROFILE = "complete-reviewed-mixed-sort-norm-admission/v3"
REVIEWED_MIXED_DECODER_RECEIPT_SCHEMA = "reviewed-mixed-legal-ir-decoder-worker-receipt/v1"
REVIEWED_DECODER_CHECKPOINT_SCHEMA = "reviewed-legal-ir-decoder-checkpoint/v1"
REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA = "reviewed-legal-ir-decoder-checkpoint/v2"
REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE = "reviewed-mixed-cycle-stage-continuation/v1"
REVIEWED_DECODER_STAGE_CONTINUATION_SCHEMA = "reviewed-decoder-stage-continuation/v1"
REVIEWED_DECODER_RECEIPT_SCHEMA = "reviewed-legal-ir-decoder-worker-receipt/v1"
REVIEWED_DECODER_SOURCE_NAMES = frozenset({"worker", "inputs", "consumer", "admission", "splits"})
MAX_REVIEWED_DECODER_STATE_BYTES = MAX_CHECKPOINT_BYTES


@dataclass(frozen=True)
class ReviewedDecoderTrainingJobSpec:
    """Closed, explicitly selected complete-target job; never a legacy sample."""
    job_id: str
    run_id: str
    base_version_id: str
    checkpoint_lineage_id: str
    output_directory: str
    code_identity: str
    stage_artifact: CheckpointArtifact
    exposure_artifact: CheckpointArtifact
    source_contexts_artifact: CheckpointArtifact
    model_artifact: CheckpointArtifact
    tokenizer_artifact: CheckpointArtifact
    license_artifact: CheckpointArtifact
    base_model_checkpoint: CheckpointArtifact
    base_optimizer_checkpoint: CheckpointArtifact
    parent_checkpoint_artifact: CheckpointArtifact
    expected_admission_inputs_sha256: str
    split_config: Mapping[str, Any]
    expected_split_config_sha256: str
    backend_identity: Mapping[str, Any]
    expected_source_sha256: Mapping[str, str]
    backend_artifacts: tuple[CheckpointArtifact, ...] = ()
    max_source_tokens: int = 8192
    max_target_tokens: int = 8192
    batch_size: int = 1
    max_steps: int = 1
    max_seconds: float = 60
    seed: int = 1729
    allow_fictional_fixture: bool = False
    schema_version: str = REVIEWED_DECODER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("job_id", "run_id", "base_version_id", "checkpoint_lineage_id", "output_directory", "code_identity"):
            _text(getattr(self, name), "reviewed_decoder." + name)
        output = Path(self.output_directory)
        if not output.is_absolute() or ".." in output.parts:
            raise TrainingJobValidationError("reviewed decoder output must be a plain absolute path")
        expected_schema = (REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA if type(self) is ReviewedDigestCacheEpochTrainingJobSpec else
            REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if type(self) is ReviewedDigestOmittedDecoderTrainingJobSpec else
            REVIEWED_MIXED_DECODER_SCHEMA_VERSION if type(self) is ReviewedMixedDecoderTrainingJobSpec else REVIEWED_DECODER_SCHEMA_VERSION)
        if self.schema_version != expected_schema:
            raise TrainingJobValidationError("explicit complete reviewed decoder schema required")
        for name in ("stage_artifact", "exposure_artifact", "source_contexts_artifact", "model_artifact",
                     "tokenizer_artifact", "license_artifact", "base_model_checkpoint", "base_optimizer_checkpoint"):
            if type(getattr(self, name)) is not CheckpointArtifact:
                raise TrainingJobValidationError("reviewed decoder " + name + " must be an exact artifact")
        if type(self.parent_checkpoint_artifact) is not CheckpointArtifact:
            raise TrainingJobValidationError("reviewed decoder parent checkpoint must be an exact artifact")
        if type(self.backend_artifacts) is not tuple or len(self.backend_artifacts) > MAX_BASE_DEPENDENCIES or any(
                type(item) is not CheckpointArtifact for item in self.backend_artifacts):
            raise TrainingJobValidationError("bounded explicit backend artifact tuple required")
        assets = (self.model_artifact, self.tokenizer_artifact, self.license_artifact, *self.backend_artifacts)
        if len({item.path for item in assets}) != len(assets) or sum(item.bytes for item in assets) > MAX_BASE_DEPENDENCY_BYTES:
            raise TrainingJobValidationError("unique bounded pretrained asset population required")
        for value, name in ((self.expected_admission_inputs_sha256, "admission"),
                            (self.expected_split_config_sha256, "split config")):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise TrainingJobValidationError("exact reviewed decoder " + name + " SHA256 required")
        if not isinstance(self.split_config, Mapping) or _digest(_json_bytes(_thaw(self.split_config))) != self.expected_split_config_sha256:
            raise TrainingJobValidationError("reviewed decoder split configuration commitment differs")
        identity = _object(self.backend_identity,
            {"backend_id", "implementation_sha256", "checkpoint_format", "target_codec", "source_conditioned", "pretrained"},
            "reviewed decoder backend identity")
        if set(identity) != {"backend_id", "implementation_sha256", "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}:
            raise TrainingJobValidationError("complete declared decoder backend identity required")
        for name in ("backend_id", "checkpoint_format"):
            _text(identity[name], "reviewed_decoder.backend_identity." + name)
        if (type(identity["implementation_sha256"]) is not str or
                re.fullmatch(r"[0-9a-f]{64}", identity["implementation_sha256"]) is None or
                identity["target_codec"] != (REVIEWED_DIGEST_OMITTED_TARGET_CODEC if type(self) in (ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec) else "complete-reviewed-norm-json/v2") or identity["source_conditioned"] is not True or
                type(identity["pretrained"]) is not bool):
            raise TrainingJobValidationError("complete source-conditioned target backend required")
        if type(self.allow_fictional_fixture) is not bool or not identity["pretrained"] and not self.allow_fictional_fixture:
            raise TrainingJobValidationError("non-pretrained backend requires explicit fictional fixture scope")
        pins = dict(self.expected_source_sha256) if isinstance(self.expected_source_sha256, Mapping) else {}
        if set(pins) != REVIEWED_DECODER_SOURCE_NAMES or any(type(value) is not str or
                re.fullmatch(r"[0-9a-f]{64}", value) is None for value in pins.values()):
            raise TrainingJobValidationError("exact complete reviewed decoder producer pins required")
        for value, low, high, name in ((self.max_source_tokens, 2, 65536, "max_source_tokens"),
                (self.max_target_tokens, 3, 65536, "max_target_tokens"), (self.batch_size, 1, 32, "batch_size"),
                (self.max_steps, 1, 10000, "max_steps"), (self.seed, 0, 2**31 - 1, "seed")):
            if type(value) is not int or not low <= value <= high:
                raise TrainingJobValidationError("invalid reviewed decoder " + name)
        if type(self.max_seconds) not in (int, float) or not math.isfinite(self.max_seconds) or not 0 < self.max_seconds <= 3600:
            raise TrainingJobValidationError("reviewed decoder max_seconds must be in (0,3600]")
        object.__setattr__(self, "split_config", _freeze(self.split_config))
        object.__setattr__(self, "backend_identity", _freeze(identity))
        object.__setattr__(self, "expected_source_sha256", _freeze(pins))

    @classmethod
    def from_dict(cls, value: Any) -> "ReviewedDecoderTrainingJobSpec":
        data = _object(value, {field.name for field in fields(cls)}, "reviewed decoder job")
        expected_schema = (REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA if cls is ReviewedDigestCacheEpochTrainingJobSpec else
            REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if cls is ReviewedDigestOmittedDecoderTrainingJobSpec else
            REVIEWED_MIXED_DECODER_SCHEMA_VERSION if cls is ReviewedMixedDecoderTrainingJobSpec else REVIEWED_DECODER_SCHEMA_VERSION)
        if data.get("schema_version") != expected_schema:
            raise TrainingJobValidationError("explicit reviewed decoder schema required")
        if cls in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec) and data.get("admission_profile") != REVIEWED_MIXED_ADMISSION_PROFILE:
            raise TrainingJobValidationError("explicit mixed-sort admission V3 profile required")
        for name in ("stage_artifact", "exposure_artifact", "source_contexts_artifact", "model_artifact",
                "tokenizer_artifact", "license_artifact", "base_model_checkpoint", "base_optimizer_checkpoint",
                "parent_checkpoint_artifact"):
            if data.get(name) is not None:
                data[name] = CheckpointArtifact.from_dict(data[name])
        if "backend_artifacts" in data:
            if type(data["backend_artifacts"]) not in (list, tuple):
                raise TrainingJobValidationError("backend artifacts must be an array")
            data["backend_artifacts"] = tuple(CheckpointArtifact.from_dict(item) for item in data["backend_artifacts"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        value = {field.name: getattr(self, field.name) for field in fields(self)}
        for name in ("stage_artifact", "exposure_artifact", "source_contexts_artifact", "model_artifact",
                "tokenizer_artifact", "license_artifact", "base_model_checkpoint", "base_optimizer_checkpoint",
                "parent_checkpoint_artifact"):
            if value[name] is not None:
                value[name] = asdict(value[name])
        value["backend_artifacts"] = [asdict(item) for item in self.backend_artifacts]
        for name in ("split_config", "backend_identity", "expected_source_sha256"):
            value[name] = _thaw(value[name])
        return value

    @property
    def canonical_sha256(self) -> str:
        return _digest(_json_bytes(self.to_dict()))

    def __reduce__(self):
        return (type(self).from_dict, (self.to_dict(),))


@dataclass(frozen=True)
class ReviewedMixedDecoderTrainingJobSpec(ReviewedDecoderTrainingJobSpec):
    """Explicit V10 job for prepared V4 inputs with homogeneous V3 admission.

    The full-nine-field codec and numerical checkpoint pair stay unchanged.
    The exact V4 training binding separates progressed checkpoints from V9.
    """
    admission_profile: str = field(kw_only=True)
    schema_version: str = REVIEWED_MIXED_DECODER_SCHEMA_VERSION
    continuation_profile: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:
            raise TrainingJobValidationError("explicit mixed-sort admission V3 profile required")
        if self.continuation_profile is not None and (type(self.continuation_profile) is not str
                or self.continuation_profile != REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE):
            raise TrainingJobValidationError("explicit mixed decoder continuation profile required")
        super().__post_init__()

    def to_dict(self) -> dict[str, Any]:
        value = super().to_dict()
        if self.continuation_profile is None:
            value.pop("continuation_profile")
        return value


@dataclass(frozen=True)
class ReviewedDigestOmittedDecoderTrainingJobSpec(ReviewedMixedDecoderTrainingJobSpec):
    """Fresh-lineage codec with ordinary exact same-input resume only."""
    schema_version: str = REVIEWED_DIGEST_OMITTED_JOB_SCHEMA

    def __post_init__(self):
        if self.continuation_profile is not None:
            raise TrainingJobValidationError("digest-omitted jobs do not authorize old-objective or source-epoch continuation")
        super().__post_init__()


@dataclass(frozen=True)
class ReviewedDecoderRuntime:
    """Trusted application injection, not a portable grant or serialized job.

    The existing admitted owner supplies both guards. This boundary records
    that they were called; it cannot independently prove a grant or license.
    The backend owns numerical execution/checkpoint format and must implement
    identity(), inspect_checkpoint(), restore_checkpoint(), train_batch() and
    snapshot_checkpoint(). No default model/provider is installed or fetched.
    """
    registry: Any
    backend: Any
    tokenizer: Any
    current_admission_provider: Callable[[], Mapping[str, Any]]
    execution_guard: Callable[[], Any]
    asset_policy_guard: Callable[[Mapping[str, Any]], Any]

    def __post_init__(self) -> None:
        for name in ("current_admission_provider", "execution_guard", "asset_policy_guard"):
            if not callable(getattr(self, name)):
                raise TrainingJobValidationError("caller-owned reviewed decoder " + name + " required")
        for name in ("identity", "validate_training_records", "inspect_checkpoint", "restore_checkpoint", "restored_checkpoint_matches", "train_batch", "snapshot_checkpoint"):
            if not callable(getattr(self.backend, name, None)):
                raise TrainingJobValidationError("explicit reviewed decoder backend." + name + " required")
        for name in ("read_artifact", "artifact_path"):
            if not callable(getattr(self.registry, name, None)):
                raise TrainingJobValidationError("read-only existing artifact registry protocol required")


def _reviewed_decoder_source_pins(*, admission_profile: str | None = None) -> dict[str, str]:
    from ...logic.autoformal import training_cycle_inputs
    if admission_profile is None:
        from ...logic.autoformal import legal_norm_content_adjudication_v1 as admission
    elif admission_profile == REVIEWED_MIXED_ADMISSION_PROFILE:
        from ...logic.autoformal import legal_reviewed_norm_admission_v3 as admission
    else:
        raise TrainingJobValidationError("explicit mixed-sort admission V3 profile required")
    from . import legal_span_consumer_binding, legal_ir_eval_splits
    modules = {"worker": Path(__file__), "inputs": Path(training_cycle_inputs.__file__),
        "consumer": Path(legal_span_consumer_binding.__file__), "admission": Path(admission.__file__),
        "splits": Path(legal_ir_eval_splits.__file__)}
    return {name: _digest(path.read_bytes()) for name, path in modules.items()}


def _reviewed_decoder_artifact(reference: CheckpointArtifact, *, limit: int = MAX_REVIEWED_DECODER_STATE_BYTES,
                               load: bool = True) -> bytes | None:
    """Authenticate ordinary immutable inputs without materializing large assets."""
    import stat
    import io
    path = Path(reference.path)
    if not path.is_absolute() or path.resolve(strict=True) != path or reference.bytes > limit:
        raise TrainingJobValidationError("reviewed decoder artifact path/byte bound differs")
    for directory in path.parents:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise TrainingJobValidationError("reviewed decoder artifact ancestry is not ordinary")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    output = None
    try:
        first = os.fstat(descriptor)
        if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_size != reference.bytes:
            raise TrainingJobValidationError("reviewed decoder artifact identity differs")
        output = io.BytesIO() if load else None
        digest, total = hashlib.sha256(), 0
        while part := os.read(descriptor, 1024**2):
            total += len(part)
            if total > reference.bytes:
                raise TrainingJobValidationError("reviewed decoder artifact grew")
            digest.update(part)
            if load:
                output.write(part)
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (total != reference.bytes or digest.hexdigest() != reference.sha256 or
                stamp(first) != stamp(os.fstat(descriptor)) or stamp(first) != stamp(path.lstat())):
            raise TrainingJobValidationError("reviewed decoder artifact changed")
        # BytesIO owns one growable buffer; getvalue returns immutable bytes
        # without retaining a separate complete inventory of read chunks.
        return output.getvalue() if load else None
    finally:
        if output is not None:
            output.close()
        os.close(descriptor)


def _reviewed_mixed_decoder_continuation_state(spec, registry, parent_reference, parent, current_binding, *, migration_backend=None):
    """Validate opt-in staged continuation before any checkpoint inspection.

    Optimizer steps remain global. Epoch/cursor are local to the complete
    currently eligible population; a changed stage always starts both at zero.
    Historical transition parents are immutable metadata, never fresh positive
    authority and never a migration across producer Source versions.
    """
    from ...logic.autoformal import training_cycle_inputs as inputs
    def need(condition, message):
        if not condition:
            raise TrainingJobValidationError(message)
    need(type(spec) is ReviewedMixedDecoderTrainingJobSpec
         and spec.continuation_profile == REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE,
         "explicit mixed decoder continuation profile required")
    need(inputs.REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE == spec.continuation_profile,
         "worker and input continuation profiles differ")
    common = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
        "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
        "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
    identity = _thaw(spec.backend_identity)
    assets = [asdict(item) for item in (spec.model_artifact, spec.tokenizer_artifact,
        spec.license_artifact, *spec.backend_artifacts)]
    pins = _thaw(spec.expected_source_sha256)
    budgets = {"max_source_tokens": spec.max_source_tokens, "max_target_tokens": spec.max_target_tokens,
               "tokenizer_contract": current_binding["tokenizer_contract"]}
    observed, seen, total_bytes = [], set(), 0
    epoch_migrations = {}

    def read_manifest(reference):
        nonlocal total_bytes
        raw = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(reference))
        total_bytes += len(raw)
        need(total_bytes <= inputs.MAX_REVIEWED_STAGE_BYTES, "continuation checkpoint metadata byte capacity exceeded")
        observed.append((reference, raw))
        return _parse_json(raw)

    def ancestry(previous, current, stage):
        try:
            return inputs.prepare_reviewed_mixed_decoder_continuation_v4(registry,
                admission_profile=spec.admission_profile, stage_artifact=stage,
                expected_stage_sha256=current["stage_artifact_sha256"],
                parent_training_binding=previous,
                expected_parent_training_binding_sha256=_digest(_json_bytes(previous)),
                current_training_binding=current,
                expected_current_training_binding_sha256=_digest(_json_bytes(current)),
                split_config=_thaw(spec.split_config), expected_split_config_sha256=spec.expected_split_config_sha256)
        except inputs.ReviewedDecoderInputValidationError as error:
            raise TrainingJobValidationError("reviewed decoder continuation ancestry differs") from error

    def validate(document, reference, *, outer=False, depth=0):
        need(depth < inputs.MAX_REVIEWED_HISTORY and reference["sha256"] not in seen,
             "continuation checkpoint metadata depth or cycle exceeded")
        seen.add(reference["sha256"])
        migrated = type(document) is dict and document.get("schema") == REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA
        revised = migrated or (type(document) is dict and document.get("schema") == REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA)
        expected = common | ({"continuation_profile", "optimizer_step_offset", "stage_continuation"} if revised else set())
        if migrated:
            expected.add("source_epoch_migration")
        need(type(document) is dict and set(document) == expected
             and document["schema"] in {REVIEWED_DECODER_CHECKPOINT_SCHEMA, REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA, REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA},
             "closed complete reviewed decoder continuation checkpoint required")
        need(document["checkpoint_lineage_id"] == spec.checkpoint_lineage_id
             and document["base_version_id"] == spec.base_version_id
             and document["backend_identity"] == identity and document["assets"] == assets
             and document["producer_pins"] == pins and document["token_budgets"] == budgets
             and type(document["batch_size"]) is int and document["batch_size"] == spec.batch_size
             and type(document["seed"]) is int and document["seed"] == spec.seed
             and document["qualified"] is False and document["promotion_performed"] is False,
             "reviewed decoder continuation numerical identities differ")
        for field in ("model_state", "optimizer_state"):
            CheckpointArtifact.from_dict(document[field])
        if outer:
            need(document["model_state"] == asdict(spec.base_model_checkpoint)
                 and document["optimizer_state"] == asdict(spec.base_optimizer_checkpoint),
                 "reviewed decoder continuation numerical pair differs")
        progress = document["progress"]
        need(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()),
             "reviewed decoder continuation progress is invalid")
        offset = document["optimizer_step_offset"] if revised else 0
        need(type(offset) is int and 0 <= offset <= progress["optimizer_steps"],
             "reviewed decoder continuation optimizer-step offset is invalid")
        if revised:
            need(document["continuation_profile"] == spec.continuation_profile,
                 "reviewed decoder checkpoint continuation profile differs")
        binding = document["training_binding"]
        if binding is None:
            need(offset == 0 and progress == {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
                 and (not revised or document["stage_continuation"] is None),
                 "only a pristine numerical parent may omit its complete training binding")
        else:
            need(type(binding) is dict and binding.get("schema") == "reviewed-decoder-training-input-receipt/v4"
                 and binding.get("profile") == inputs.REVIEWED_MIXED_DECODER_INPUT_PROFILE
                 and binding.get("admission_profile") == spec.admission_profile
                 and type(binding.get("record_count")) is int and 0 < binding["record_count"] <= inputs.MAX_REVIEWED_CYCLE_ROWS,
                 "progressed continuation parent must retain a same-domain V4 training binding")
            count = binding["record_count"]
            need(progress["row_cursor"] < count and progress["row_cursor"] % spec.batch_size == 0
                 and progress["optimizer_steps"] == offset + progress["epochs_completed"] * math.ceil(count/spec.batch_size)
                     + progress["row_cursor"] // spec.batch_size,
                 "reviewed decoder continuation global/local progress differs")
        if migrated:
            migration_ref = asdict(CheckpointArtifact.from_dict(document["source_epoch_migration"]))
            if migration_ref["sha256"] not in epoch_migrations:
                epoch_migrations[migration_ref["sha256"]] = _reviewed_epoch_validate_receipt(
                    migration_ref, migration_backend, expected_spec=spec)
            migration = epoch_migrations[migration_ref["sha256"]]
            need(progress["optimizer_steps"] >= migration["original_progress"]["optimizer_steps"],
                 "source-epoch migration cannot rewind global optimizer steps")
        transition = document["stage_continuation"] if revised else None
        if transition is None:
            need(offset == 0, "nonzero optimizer-step offset requires its authenticated stage continuation")
        else:
            fields = {"schema", "parent_checkpoint_artifact", "parent_training_binding_sha256",
                "current_training_binding_sha256", "global_optimizer_step_offset", "stage_ancestry"}
            need(type(transition) is dict and set(transition) == fields
                 and transition["schema"] == REVIEWED_DECODER_STAGE_CONTINUATION_SCHEMA
                 and binding is not None and type(transition["global_optimizer_step_offset"]) is int
                 and transition["global_optimizer_step_offset"] == offset
                 and transition["current_training_binding_sha256"] == _digest(_json_bytes(binding)),
                 "closed persisted decoder stage continuation differs")
            prior_ref = asdict(CheckpointArtifact.from_dict(transition["parent_checkpoint_artifact"]))
            prior = read_manifest(prior_ref)
            validate(prior, prior_ref, depth=depth+1)
            need(prior["training_binding"] is not None and offset == prior["progress"]["optimizer_steps"]
                 and transition["parent_training_binding_sha256"] == _digest(_json_bytes(prior["training_binding"])),
                 "persisted optimizer-step offset is not bound to its actual historical checkpoint")
            proof = transition["stage_ancestry"]
            need(type(proof) is dict and "successor_stage" in proof,
                 "persisted stage continuation ancestry is absent")
            replay = ancestry(prior["training_binding"], binding, proof["successor_stage"])
            need(_json_bytes(replay) == _json_bytes(proof), "persisted decoder stage ancestry changed")
        return offset

    parent_reference = asdict(parent_reference) if type(parent_reference) is CheckpointArtifact else parent_reference
    parent_offset = validate(parent, parent_reference, outer=True)
    progress = dict(parent["progress"])
    transition = parent.get("stage_continuation")
    changed = parent["training_binding"] is not None and _json_bytes(parent["training_binding"]) != _json_bytes(current_binding)
    if changed:
        need(progress["optimizer_steps"] > 0, "changed-stage continuation requires a progressed numerical parent")
        proof = ancestry(parent["training_binding"], current_binding, asdict(spec.stage_artifact))
        parent_offset = progress["optimizer_steps"]
        progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": parent_offset}
        transition = {"schema": REVIEWED_DECODER_STAGE_CONTINUATION_SCHEMA,
            "parent_checkpoint_artifact": parent_reference,
            "parent_training_binding_sha256": _digest(_json_bytes(parent["training_binding"])),
            "current_training_binding_sha256": _digest(_json_bytes(current_binding)),
            "global_optimizer_step_offset": parent_offset, "stage_ancestry": proof}
    for reference, raw in observed:
        need(_reviewed_decoder_artifact(CheckpointArtifact.from_dict(reference)) == raw,
             "continuation historical checkpoint metadata changed")
    return {"progress": progress, "optimizer_step_offset": parent_offset,
        "stage_continuation": transition, "stage_transition_performed": changed,
        "source_epoch_migration": parent.get("source_epoch_migration")}


def _execute_reviewed_decoder_job(spec: ReviewedDecoderTrainingJobSpec, runtime: ReviewedDecoderRuntime,
                                  job_file_sha256: str | None) -> dict[str, Any]:
    """Consume full current-reviewed targets via one declared numerical backend.

    This is a software execution/checkpoint boundary. Backend reports and opaque
    state bytes do not prove pretrained quality, semantic fidelity or convergence.
    There is no corpus promotion, registry write, network loader or proof claim.
    """
    import random
    import stat
    from ...logic.autoformal import training_cycle_inputs as inputs
    if type(runtime) is not ReviewedDecoderRuntime:
        raise TrainingJobValidationError("explicit reviewed decoder runtime required before model work")
    if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec or (type(runtime.backend) is TorchReviewedDecoderBackend and runtime.backend.cache_source_epoch_marker is not None):
        _reviewed_digest_cache_epoch_require_job(spec, runtime.backend)
    prepared = None
    continuation_replay = None
    checkpoint_limit = MAX_REVIEWED_DECODER_STATE_BYTES
    digest_omitted = type(spec) in (ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec)
    mixed = type(spec) in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec)
    checkpoint_schema = REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA if digest_omitted else REVIEWED_DECODER_CHECKPOINT_SCHEMA
    admission_profile = spec.admission_profile if mixed else None
    guard_calls = {"execution": 0, "asset_policy": 0, "current_admission": 0}
    identity = _thaw(spec.backend_identity)
    assets = (spec.model_artifact, spec.tokenizer_artifact, spec.license_artifact, *spec.backend_artifacts)
    source_pins = _thaw(spec.expected_source_sha256)
    exposure_raw = _reviewed_decoder_artifact(spec.exposure_artifact)
    contexts_raw = _reviewed_decoder_artifact(spec.source_contexts_artifact)
    exposure, contexts = _parse_json(exposure_raw), _parse_json(contexts_raw)
    if _json_bytes(exposure) != exposure_raw or _json_bytes(contexts) != contexts_raw:
        raise TrainingJobValidationError("exact canonical reviewed exposure/context artifacts required")

    def current():
        nonlocal prepared, checkpoint_limit
        runtime.execution_guard()
        guard_calls["execution"] += 1
        if _reviewed_decoder_source_pins(admission_profile=admission_profile) != source_pins:
            raise TrainingJobValidationError("reviewed decoder producer changed")
        # Caller-owned model/license policy is required, not inferred from a
        # manifest flag, backend return value or a fictional review fixture.
        runtime.asset_policy_guard(spec.to_dict())
        guard_calls["asset_policy"] += 1
        if _parse_json(_json_bytes(runtime.backend.identity())) != identity:
            raise TrainingJobValidationError("declared reviewed decoder backend identity differs")
        # The explicitly profiled numerical backend already authenticates its
        # model type and CPU/BF16 storage before selecting the larger bound.
        # Ordinary and caller-defined backends retain the legacy state bound.
        checkpoint_limit = (TorchReviewedDecoderBackend._checkpoint_byte_limit(runtime.backend)
            if type(runtime.backend) is TorchReviewedDecoderBackend
            else MAX_REVIEWED_DECODER_STATE_BYTES)
        for item in assets:
            numeric_asset = item is spec.model_artifact or item in spec.backend_artifacts
            _reviewed_decoder_artifact(item,
                limit=checkpoint_limit if numeric_asset else MAX_CHECKPOINT_BYTES, load=False)
        if (_reviewed_decoder_artifact(spec.exposure_artifact) != exposure_raw or
                _reviewed_decoder_artifact(spec.source_contexts_artifact) != contexts_raw):
            raise TrainingJobValidationError("reviewed decoder context/exposure changed")
        admission = runtime.current_admission_provider()
        guard_calls["current_admission"] += 1
        try:
            prepare = (inputs.prepare_reviewed_mixed_decoder_digest_omitted_inputs_v1 if digest_omitted else
                       inputs.prepare_reviewed_mixed_decoder_training_inputs_v4 if mixed
                       else inputs.prepare_reviewed_decoder_training_inputs)
            profile_options = {"admission_profile": admission_profile} if mixed else {}
            value = prepare(runtime.registry, **profile_options,
                stage_artifact=asdict(spec.stage_artifact), expected_stage_sha256=spec.stage_artifact.sha256,
                current_admission_inputs=admission,
                expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,
                exposure_records=exposure, expected_exposure_sha256=spec.exposure_artifact.sha256,
                source_contexts=contexts, expected_source_contexts_sha256=spec.source_contexts_artifact.sha256,
                split_config=_thaw(spec.split_config), expected_split_config_sha256=spec.expected_split_config_sha256,
                tokenizer=runtime.tokenizer, max_source_tokens=spec.max_source_tokens,
                max_target_tokens=spec.max_target_tokens, allow_fictional_fixture=spec.allow_fictional_fixture)
        except inputs.ReviewedDecoderInputValidationError as error:
            # Only the input owner's explicit decoder validation type crosses
            # this boundary. Foreign callback/registry errors retain identity.
            raise TrainingJobValidationError("current reviewed decoder inputs changed or unsupported") from error
        receipt = value.get("receipt", {})
        profile = (value.get("schema"), receipt.get("schema"), receipt.get("profile"))
        single_component = profile == (inputs.REVIEWED_DECODER_INPUT_SCHEMA,
            "reviewed-decoder-training-input-receipt/v2", inputs.REVIEWED_DECODER_INPUT_PROFILE)
        signed_components = (profile == (inputs.REVIEWED_COMPONENT_DECODER_INPUT_SCHEMA,
            "reviewed-decoder-training-input-receipt/v3", inputs.REVIEWED_COMPONENT_DECODER_INPUT_PROFILE)
            and receipt.get("source_context_profile") == inputs.REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE)
        mixed_components = (profile == (inputs.REVIEWED_MIXED_DECODER_INPUT_SCHEMA,
            "reviewed-decoder-training-input-receipt/v4", inputs.REVIEWED_MIXED_DECODER_INPUT_PROFILE)
            and receipt.get("admission_profile") == admission_profile
            and receipt.get("source_context_profile") == inputs.REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE) if mixed else False
        projected_components = (profile == (inputs.REVIEWED_DIGEST_OMITTED_INPUT_SCHEMA,
            inputs.REVIEWED_DIGEST_OMITTED_INPUT_RECEIPT_SCHEMA, inputs.REVIEWED_DIGEST_OMITTED_INPUT_PROFILE)
            and receipt.get("admission_profile") == admission_profile
            and receipt.get("source_context_profile") == inputs.REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE)
        if (not (projected_components if digest_omitted else mixed_components if mixed else single_component or signed_components)
                or receipt.get("target_codec") != (REVIEWED_DIGEST_OMITTED_TARGET_CODEC if digest_omitted else inputs.REVIEWED_DECODER_TARGET_CODEC)
                or receipt.get("source_profile") != inputs.REVIEWED_DECODER_SOURCE_PROFILE
                or receipt.get("semantic_selection_supported") is not False):
            raise TrainingJobValidationError("explicit caller-known selection-context training inputs required")
        if prepared is None:
            prepared = value
        elif _json_bytes(value) != _json_bytes(prepared):
            raise TrainingJobValidationError("current reviewed decoder inputs changed before publication")
        if continuation_replay is not None:
            continuation_replay(value["receipt"])
            # Registry replay and backend identity are caller-owned callbacks.
            # Close their effects before inspection/restoration or another
            # update: Source pins are the final callback-free observation.
            if _parse_json(_json_bytes(runtime.backend.identity())) != identity:
                raise TrainingJobValidationError("reviewed decoder backend identity changed during continuation replay")
            if _reviewed_decoder_source_pins(admission_profile=admission_profile) != source_pins:
                raise TrainingJobValidationError("reviewed decoder producer changed during continuation replay")
        return value

    # All rows, legal-use/split/context/codec/budget constraints are checked
    # before loading or restoring either model or optimizer state.
    data = current()
    records = data["records"]
    if type(records) is not list or not records:
        raise TrainingJobValidationError("nonempty complete reviewed training records required")
    validation_rows = _parse_json(_json_bytes(records))
    validation_sha = _digest(_json_bytes(validation_rows))
    runtime.backend.validate_training_records(validation_rows, max_source_tokens=spec.max_source_tokens,
                                             max_target_tokens=spec.max_target_tokens)
    if _digest(_json_bytes(validation_rows)) != validation_sha:
        raise TrainingJobValidationError("backend mutated complete preflight records")
    current()
    model_raw = _reviewed_decoder_artifact(spec.base_model_checkpoint, limit=checkpoint_limit)
    optimizer_raw = _reviewed_decoder_artifact(spec.base_optimizer_checkpoint, limit=checkpoint_limit)
    parent = None
    continuation_enabled = mixed and spec.continuation_profile is not None
    optimizer_step_offset, stage_continuation, continuation_state = 0, None, None
    source_epoch_migration = None
    progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    if spec.parent_checkpoint_artifact is not None:
        parent_raw = _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)
        parent = _parse_json(parent_raw)
        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:
            parent = _reviewed_digest_cache_epoch_ancestry(spec, runtime.backend, parent, data["receipt"])
            frozen_cache_parent = _json_bytes(parent)
            def replay_cache_epoch(binding):
                observed = _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)
                if observed != parent_raw:
                    raise TrainingJobValidationError("digest cache ancestry parent changed")
                normalized = _reviewed_digest_cache_epoch_ancestry(spec, runtime.backend, _parse_json(observed), binding)
                if _json_bytes(normalized) != frozen_cache_parent:
                    raise TrainingJobValidationError("digest cache ancestry changed during execution")
            continuation_replay = replay_cache_epoch
        if continuation_enabled:
            continuation_state = _reviewed_mixed_decoder_continuation_state(spec, runtime.registry,
                spec.parent_checkpoint_artifact, parent, data["receipt"], migration_backend=runtime.backend)
            progress = dict(continuation_state["progress"])
            optimizer_step_offset = continuation_state["optimizer_step_offset"]
            stage_continuation = continuation_state["stage_continuation"]
            source_epoch_migration = continuation_state["source_epoch_migration"]
            frozen_continuation = _json_bytes(continuation_state)
            def replay_continuation(binding):
                observed = _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)
                if observed != parent_raw:
                    raise TrainingJobValidationError("continuation parent checkpoint metadata changed")
                current_state = _reviewed_mixed_decoder_continuation_state(spec, runtime.registry,
                    spec.parent_checkpoint_artifact, _parse_json(observed), binding, migration_backend=runtime.backend)
                if _json_bytes(current_state) != frozen_continuation:
                    raise TrainingJobValidationError("continuation ancestry or offset changed before publication")
            continuation_replay = replay_continuation
        else:
            expected_fields = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
                "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
                "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
            if type(parent) is not dict or set(parent) != expected_fields or parent["schema"] != checkpoint_schema:
                raise TrainingJobValidationError("closed complete reviewed decoder parent checkpoint required")
            if (parent["checkpoint_lineage_id"] != spec.checkpoint_lineage_id or parent["base_version_id"] != spec.base_version_id or
                    parent["backend_identity"] != identity or parent["assets"] != [asdict(item) for item in assets] or
                    parent["model_state"] != asdict(spec.base_model_checkpoint) or
                    parent["optimizer_state"] != asdict(spec.base_optimizer_checkpoint) or
                    (parent["training_binding"] != data["receipt"] and not (parent["training_binding"] is None and
                        parent["progress"] == {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0})) or
                    parent["token_budgets"] != {"max_source_tokens": spec.max_source_tokens, "max_target_tokens": spec.max_target_tokens,
                        "tokenizer_contract": data["receipt"]["tokenizer_contract"]} or parent["batch_size"] != spec.batch_size or
                    parent["seed"] != spec.seed or parent["producer_pins"] != source_pins or
                    parent["qualified"] is not False or parent["promotion_performed"] is not False):
                raise TrainingJobValidationError("reviewed decoder exact-resume identities differ")
            progress = dict(parent["progress"])
    if (set(progress) != {"epochs_completed", "row_cursor", "optimizer_steps"} or
            any(type(value) is not int or not 0 <= value <= 10**9 for value in progress.values()) or
            progress["row_cursor"] >= len(records) or progress["row_cursor"] % spec.batch_size or
            progress["optimizer_steps"] != optimizer_step_offset + progress["epochs_completed"] * math.ceil(len(records) / spec.batch_size) +
                progress["row_cursor"] // spec.batch_size):
        raise TrainingJobValidationError("reviewed decoder step/cursor identity differs")
    # Reserve capacity for the complete requested update window before any
    # restore or fitting. A timed early stop does not authorize an unresumable
    # successor whose counters exceed the checkpoint contract.
    if progress["optimizer_steps"] + spec.max_steps > 10**9:
        raise TrainingJobValidationError("reviewed decoder progress capacity exhausted before update")
    initial_progress = dict(progress)
    current()
    checkpoint_info = runtime.backend.inspect_checkpoint(model_raw, optimizer_raw)
    if type(checkpoint_info) is not dict or set(checkpoint_info) != {"optimizer_steps"} or checkpoint_info["optimizer_steps"] != progress["optimizer_steps"] or type(checkpoint_info["optimizer_steps"]) is not int:
        raise TrainingJobValidationError("backend checkpoint optimizer step differs")
    output = Path(spec.output_directory)
    if os.path.lexists(output) or output.parent.resolve(strict=True) != output.parent:
        raise TrainingJobValidationError("fresh ordinary reviewed decoder output required")
    for directory in output.parents:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise TrainingJobValidationError("ordinary reviewed decoder output ancestry required")
    output.mkdir(mode=0o700, exist_ok=False)
    reports, restore_calls, restore_attempts = [], 0, 0
    started, stop_reason = time.monotonic(), "step_limit"
    try:
        current()
        if time.monotonic() - started >= spec.max_seconds:
            raise TrainingJobValidationError("deadline before checkpoint restore")
        # Restoration can change model state before an optimizer/RNG failure.
        # Record the attempt before entering the caller-owned mutating hook.
        restore_attempts += 1
        runtime.backend.restore_checkpoint(model_raw, optimizer_raw)
        restore_calls += 1
        if runtime.backend.restored_checkpoint_matches(model_raw, optimizer_raw) is not True:
            raise TrainingJobValidationError("restored model/optimizer pair did not roundtrip exactly")
        current()
        for _ in range(spec.max_steps):
            if time.monotonic() - started >= spec.max_seconds:
                stop_reason = "deadline_before_batch"
                break
            current()
            if time.monotonic() - started >= spec.max_seconds:
                stop_reason = "deadline_after_current_guard_before_batch"
                break
            order = list(range(len(records)))
            random.Random(spec.seed + progress["epochs_completed"]).shuffle(order)
            indices = order[progress["row_cursor"]:progress["row_cursor"] + spec.batch_size]
            # Only complete current-admitted training records reach this hook;
            # no history, assessment transport, heldout targets or model lookup.
            batch = _parse_json(_json_bytes([records[index] for index in indices]))
            before_batch = _digest(_json_bytes(batch))
            report = runtime.backend.train_batch(batch)
            if _digest(_json_bytes(batch)) != before_batch:
                raise TrainingJobValidationError("backend mutated detached reviewed training records")
            if type(report) is not dict or set(report) - ({"loss", "gradient_norm", "optimizer_steps",
                    "trainable_parameter_count", "gradient_parameter_count"} |
                    set(_EXPECTED_TEACHER_FORCED_COUNT_KEYS)):
                raise TrainingJobValidationError("bounded numeric backend report required")
            for value in report.values():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise TrainingJobValidationError("finite numeric backend report required")
            reports.append(_parse_json(_json_bytes(report)))
            progress["optimizer_steps"] += 1
            progress["row_cursor"] += len(indices)
            if progress["row_cursor"] == len(records):
                progress["epochs_completed"] += 1
                progress["row_cursor"] = 0
            current()
        if not reports:
            raise TrainingJobValidationError("no decoder update call completed within declared boundary")
        current()
        snapshot = runtime.backend.snapshot_checkpoint()
        if type(snapshot) is not dict or set(snapshot) != {"model_state", "optimizer_state"} or any(
                type(snapshot[key]) is not bytes or not 0 < len(snapshot[key]) <= checkpoint_limit
                for key in snapshot):
            raise TrainingJobValidationError("bounded actual model and optimizer checkpoint bytes required")
        snapshot_info = runtime.backend.inspect_checkpoint(snapshot["model_state"], snapshot["optimizer_state"])
        if snapshot_info != {"optimizer_steps": progress["optimizer_steps"]} or type(snapshot_info.get("optimizer_steps")) is not int:
            raise TrainingJobValidationError("exported backend optimizer step differs")
        current()
        if (_reviewed_decoder_artifact(spec.base_model_checkpoint, limit=checkpoint_limit) != model_raw or
                _reviewed_decoder_artifact(spec.base_optimizer_checkpoint, limit=checkpoint_limit) != optimizer_raw):
            raise TrainingJobValidationError("base model/optimizer checkpoint changed during update")
        if spec.parent_checkpoint_artifact is not None:
            _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)
        model = _write_exclusive(output / "model.checkpoint", snapshot["model_state"])
        optimizer = _write_exclusive(output / "optimizer.checkpoint", snapshot["optimizer_state"])
        for item in (model, optimizer):
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(item), limit=checkpoint_limit)
        checkpoint = {"schema": checkpoint_schema, "checkpoint_lineage_id": spec.checkpoint_lineage_id,
            "base_version_id": spec.base_version_id, "backend_identity": identity,
            "assets": [asdict(item) for item in assets], "training_binding": data["receipt"],
            "model_state": model, "optimizer_state": optimizer, "progress": progress,
            "batch_size": spec.batch_size, "seed": spec.seed,
            "token_budgets": {"max_source_tokens": spec.max_source_tokens, "max_target_tokens": spec.max_target_tokens,
                "tokenizer_contract": data["receipt"]["tokenizer_contract"]},
            "parent_checkpoint_sha256": spec.parent_checkpoint_artifact.sha256 if spec.parent_checkpoint_artifact else None,
            "producer_pins": source_pins, "qualified": False, "promotion_performed": False}
        if continuation_enabled:
            checkpoint.update(schema=REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA,
                continuation_profile=spec.continuation_profile, optimizer_step_offset=optimizer_step_offset,
                stage_continuation=stage_continuation)
            if source_epoch_migration is not None:
                checkpoint.update(schema=REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA,
                    source_epoch_migration=source_epoch_migration)
        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:
            checkpoint.update(schema=REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA,
                cache_source_epoch_migration=asdict(spec.cache_source_epoch_migration),
                cache_epoch_parent_checkpoint_artifact=asdict(spec.parent_checkpoint_artifact))
        current()
        checkpoint_ref = _write_exclusive(output / "reviewed-decoder-checkpoint.json", _json_bytes(checkpoint))
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(checkpoint_ref))
        current()
        receipt = {"schema_version": (REVIEWED_DIGEST_OMITTED_WORKER_RECEIPT_SCHEMA if digest_omitted else REVIEWED_MIXED_DECODER_RECEIPT_SCHEMA if mixed else REVIEWED_DECODER_RECEIPT_SCHEMA),
            "job_id": spec.job_id, "run_id": spec.run_id,
            "job_spec_sha256": spec.canonical_sha256, "job_file_sha256": job_file_sha256,
            "code_identity": spec.code_identity, "base_version_id": spec.base_version_id,
            "base_model_checkpoint": asdict(spec.base_model_checkpoint),
            "base_optimizer_checkpoint": asdict(spec.base_optimizer_checkpoint), "candidate": checkpoint_ref,
            "model_checkpoint": model, "optimizer_checkpoint": optimizer, "complete_training_binding": data["receipt"],
            "prepared_inputs_sha256": data["prepared_sha256"], "backend_identity_declared": identity,
            "backend_train_batch_calls": len(reports), "backend_restore_calls": restore_calls,
            "backend_restore_attempts": restore_attempts,
            "backend_reported_metrics": reports, "backend_reported_optimizer_steps": snapshot_info["optimizer_steps"],
            "worker_progress": progress, "initial_progress": initial_progress,
            "model_bytes_changed": snapshot["model_state"] != model_raw,
            "optimizer_bytes_changed": snapshot["optimizer_state"] != optimizer_raw,
            "guard_call_counts": guard_calls, "stopped_reason": stop_reason,
            "elapsed_seconds": time.monotonic() - started, "producer_pins": source_pins,
            "checkpoint_resume_contract": "exact_input_and_backend_state_comparison_not_deterministic_reserialization_or_independent_numeric_proof",
            "deadline_scope": "soft_restore_update_boundaries_after_preflight_not_an_interrupt_or_resource_grant",
            "guard_scope": "trusted_caller_supplied_existing_execution_and_asset_policy_guards",
            "backend_trust_scope": "caller_owns_numeric_execution_tokenizer_assets_license_and_checkpoint_format",
            "physical_model_assets_verified": False, "pretrained_quality_verified": False,
            "numerical_update_independently_verified": False, "optimizer_resume_independently_verified": False,
            "legal_meaning_verified": False, "source_fidelity_proved": False, "convergence_proved": False,
            "semantic_selection_supported": False, "competing_meaning_policy": "unprovided",
            "qualified": False, "admitted": False, "promotion_performed": False,
            "corpus_admitted": False, "registry_modified": False, "downloads_performed": False,
            "legacy_projection_sample_conversion_performed": False}
        if continuation_enabled:
            receipt.update(continuation_profile=spec.continuation_profile,
                checkpoint_schema=REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA,
                optimizer_step_offset=optimizer_step_offset, stage_continuation=stage_continuation,
                stage_transition_performed=continuation_state["stage_transition_performed"],
                changed_population_initial_cursor_zero=continuation_state["stage_transition_performed"])
        if source_epoch_migration is not None:
            receipt["source_epoch_migration"] = source_epoch_migration
            receipt["checkpoint_schema"] = REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA
        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:
            receipt.update(cache_source_epoch_migration=asdict(spec.cache_source_epoch_migration),
                checkpoint_schema=REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA,
                cache_source_epoch_profile=_thaw(runtime.backend.cache_source_epoch_marker)["profile"])
        if mixed:
            receipt["admission_profile"] = admission_profile
        _write_exclusive(output / "receipt.json", _json_bytes(receipt))
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return receipt
    except BaseException as error:
        # Preserve partial files/state; no retry, rollback or promotion. The
        # injected backend object remains caller-owned when its update fails.
        failure = {"schema": "reviewed-decoder-worker-failure/v1", "job_id": spec.job_id,
            "error_type": type(error).__name__, "completed_backend_calls": len(reports),
            "worker_progress": progress, "partial_output_preserved": True,
            "backend_restore_attempts": restore_attempts, "completed_backend_restore_calls": restore_calls,
            "caller_owned_backend_may_have_changed": restore_attempts > 0,
            "qualified": False, "promotion_performed": False}
        try:
            _write_exclusive(output / "failure.json", _json_bytes(failure))
        except BaseException as publication_error:
            error.add_note("failed to retain failure metadata: " + type(publication_error).__name__)
        raise


def _require_tree_pin() -> dict[str, str]:
    # Import the pin before the model. A process that already imported HACC's
    # parser must fail; changing sys.path here would not repair that process.
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree

    return require_workspace_logic_tree()


@contextmanager
def _worker_environment():
    settings = {"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
                "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
                "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1"}
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield settings
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _effective_constructor_config(model_class: Any, supplied: Mapping[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(model_class.__init__)
    unsupported = {"self", "state", "feature_codec", "legacy_embedding_adapters", "legacy_distillation_adapters"}
    allowed = set(signature.parameters) - unsupported
    if set(supplied) - allowed:
        raise TrainingJobValidationError(f"unknown or unsupported autoencoder_config fields: {sorted(set(supplied) - allowed)}")
    result: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name in {"self", "state"}:
            continue
        value = _thaw(supplied.get(name, parameter.default))
        if name == "compute_device":
            if value not in {"auto", "cpu", "python"}:
                raise TrainingJobValidationError("worker compute_device must be auto, cpu, or python")
        elif name == "modal_families":
            if value is not None and (not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value)):
                raise TrainingJobValidationError("modal_families must be a nonempty string array")
        elif isinstance(parameter.default, (float, int)):
            _number(value, f"autoencoder_config.{name}", integer=isinstance(parameter.default, int))
            if name.endswith("abstention_threshold") and value > 1:
                raise TrainingJobValidationError(f"autoencoder_config.{name} must be <= 1")
        elif isinstance(parameter.default, str):
            _text(value, f"autoencoder_config.{name}", empty=True)
        result[name] = value
    return result


def _write_exclusive(path: Path, raw: bytes) -> dict[str, Any]:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": str(path), "sha256": _digest(raw), "bytes": len(raw)}


def _memory_observation() -> dict[str, Any]:
    """Observed process pages, not inferred numeric-buffer or system memory."""
    result: dict[str, Any] = {}
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result.update(minor_faults=usage.ru_minflt, major_faults=usage.ru_majflt)
        if platform.system() == "Linux":
            result["max_rss_kib"] = usage.ru_maxrss
        for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in {"Rss", "Pss", "Private_Clean", "Private_Dirty", "Shared_Clean", "Shared_Dirty"}:
                result[key.lower() + "_kib"] = int(value.split()[0])
    except (ImportError, OSError, ValueError):
        result["page_accounting_unavailable"] = True
    return result


def _hydrate_target_operation(snapshot: Any, *, defer_gc: bool,
                              hydrate: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    """Optionally defer cyclic scans in an isolated native bundle worker.

    The bundle still checks every requested sample, shard and complete target.
    Its tagged JSON has no back-references; temporary graphs are reclaimed by
    reference counting. The explicit post-load collection is timed here, before
    training, so any deferred cleanup is included in hydration cost. Public
    loaders and embedded/injected workers retain their normal GC policy.
    """
    from .legal_ir_target_bundle import TargetBundle

    started = time.perf_counter()
    enabled = gc.isenabled()
    stats_before = gc.get_stats()
    telemetry = {
        "policy": "defer_during_verified_bundle_hydration_v1" if defer_gc else "default",
        "requested": defer_gc, "applied": False, "skip_reason": None,
        "referenced_uncompressed_bytes": None,
        "max_referenced_uncompressed_bytes": MAX_GC_DEFERRED_TARGET_BYTES,
        "gc_enabled_before": enabled, "gc_threshold_before": list(gc.get_threshold()),
        "gc_stats_before": stats_before, "explicit_collection_performed": False,
        "collection_seconds": 0.0,
    }
    reason = None
    if not defer_gc:
        reason = "not_requested"
    elif type(snapshot) is not TargetBundle:
        reason = "unsupported_snapshot"
    elif platform.python_implementation() != "CPython":
        reason = "unsupported_python"
    elif multiprocessing.parent_process() is None or multiprocessing.get_start_method(allow_none=True) != "spawn":
        reason = "not_spawn_worker"
    elif threading.current_thread() is not threading.main_thread():
        reason = "not_main_thread"
    elif threading.active_count() != 1:
        reason = "other_python_threads"
    elif not enabled:
        reason = "gc_already_disabled"
    elif gc.get_debug():
        reason = "gc_debug_enabled"
    elif gc.callbacks:
        reason = "gc_callbacks_present"
    else:
        expanded = snapshot.statistics.get("referenced_uncompressed_target_bytes")
        telemetry["referenced_uncompressed_bytes"] = expanded
        if type(expanded) is not int or expanded <= 0:
            reason = "invalid_expanded_byte_count"
        elif expanded > MAX_GC_DEFERRED_TARGET_BYTES:
            reason = "expanded_byte_limit"
    telemetry["skip_reason"] = reason
    telemetry["applied"] = reason is None
    hydrate_started = time.perf_counter()
    if reason is None:
        # No callbacks, foreign Python threads or embedded callers are eligible.
        # Restore before propagating any exception; never replace a hydration
        # failure with a cleanup exception or perform forced GC on that path.
        try:
            gc.disable()
            targets = hydrate()
        finally:
            gc.enable() if enabled else gc.disable()
        telemetry["hydrate_seconds"] = time.perf_counter() - hydrate_started
        collection_started = time.perf_counter()
        try:
            gc.collect(2)
            telemetry["explicit_collection_performed"] = True
        finally:
            gc.enable() if enabled else gc.disable()
        telemetry["collection_seconds"] = time.perf_counter() - collection_started
    else:
        targets = hydrate()
        telemetry["hydrate_seconds"] = time.perf_counter() - hydrate_started
    stats_after = gc.get_stats()
    telemetry.update(gc_enabled_after=gc.isenabled(), gc_threshold_after=list(gc.get_threshold()),
                     gc_stats_after=stats_after,
                     gc_stats_delta=[{key: after[key] - before[key] for key in after}
                                     for before, after in zip(stats_before, stats_after)],
                     total_seconds=time.perf_counter() - started)
    return targets, telemetry


def _hydrate_shared_targets(snapshot: Any, members: Any, config: Any, *,
                            defer_gc: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep ordinary full hydration and its GC policy unchanged."""
    return _hydrate_target_operation(
        snapshot, defer_gc=defer_gc,
        hydrate=lambda: snapshot.targets_for(members, config=config))


def _target_reduction_skip_reason(snapshot: Any, trainer: Any) -> str | None:
    from .legal_ir_target_bundle import TargetBundle

    if trainer is not None:
        return "injected_trainer"
    if type(snapshot) is not TargetBundle:
        return "unsupported_snapshot"
    if multiprocessing.parent_process() is None or multiprocessing.get_start_method(allow_none=True) != "spawn":
        return "not_spawn_worker"
    if threading.current_thread() is not threading.main_thread():
        return "not_main_thread"
    if threading.active_count() != 1:
        return "other_python_threads"
    return None


def _stream_reduced_shared_targets(snapshot: Any, members: Any, config: Any, *,
                                   defer_gc: bool, prepare: Callable[..., Any]) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Bound rich-graph retention, at the cost of a second validated decode.

    Only the isolated native worker calls this helper. The first pass validates
    the complete selection before any reducer hashing/conversion. The second
    pass retains immutable capsules only. Unsupported envelopes take the full
    loader/reducer path; nothing partial is installed. The reducer's extra
    hashing/conversion runs outside our GC-deferral scopes, preserving an
    originally disabled GC state. Existing full-validation document hashing
    remains inside hydration as before.
    These are memory-oriented mechanics, not a native speed qualification.
    """
    from . import _autoencoder_prepared_targets as reduction

    started = time.perf_counter()
    observations = []
    stream = {"policy": "two_pass_verified_target_reduction_v1",
              "validation_pass_targets": 0, "conversion_pass_targets": 0,
              "fallback_full_hydration": False, "fallback_reason": None, "fallback_hydrated_targets": 0,
              "validation_authority": False, "native_performance_qualified": False,
              "validation_pass_seconds": 0.0, "conversion_hydration_seconds": 0.0,
              "reduction_seconds": 0.0, "release_seconds": 0.0,
              "release_scope": "caller reference unlink only; prior graph cleanup occurs on iterator advance or finalization",
              "iterator_finalization_seconds": 0.0}
    first_reason = None

    def validate_selection():
        nonlocal first_reason
        iterator = snapshot.iter_targets_for(members, config=config)
        try:
            for sample_id, target in iterator:
                reason = reduction._eligible(target, sample_id)
                if first_reason is None and reason is not None:
                    first_reason = reason
                stream["validation_pass_targets"] += 1
                # Both caller and iterator release this graph before next decode.
                del target
        finally:
            iterator.close()

    _, observation = _hydrate_target_operation(
        snapshot, defer_gc=defer_gc, hydrate=validate_selection)
    observations.append(observation)
    stream["validation_pass_seconds"] = observation["total_seconds"]
    if not reduction._native_classes_unchanged():
        first_reason = "native_class_contract_changed"
    if not members:
        first_reason = "non_native_or_empty_target_mapping"

    def fallback(reason):
        stream["fallback_full_hydration"] = True
        stream["fallback_reason"] = reason
        full, observation = _hydrate_shared_targets(snapshot, members, config, defer_gc=defer_gc)
        observations.append(observation)
        stream["fallback_hydrated_targets"] = len(full)
        stream["conversion_hydration_seconds"] += observation["total_seconds"]
        reduce_started = time.perf_counter()
        result, telemetry = prepare(full)
        stream["reduction_seconds"] += time.perf_counter() - reduce_started
        return result, telemetry

    if first_reason is not None:
        targets, telemetry = fallback(first_reason)
    else:
        prepared = {}
        telemetry = {"applied": True, "skip_reason": None,
                     "original_target_count": len(members), "prepared_target_count": 0,
                     "preparation_seconds": 0.0, "hash_seconds": 0.0}
        iterator = snapshot.iter_targets_for(members, config=config)
        late_reason = None
        try:
            for _ in members:
                pair, observation = _hydrate_target_operation(
                    snapshot, defer_gc=defer_gc, hydrate=lambda: next(iterator))
                observations.append(observation)
                stream["conversion_hydration_seconds"] += observation["total_seconds"]
                sample_id, target = pair
                del pair
                stream["conversion_pass_targets"] += 1
                reduce_started = time.perf_counter()
                converted, details = prepare({sample_id: target})
                stream["reduction_seconds"] += time.perf_counter() - reduce_started
                telemetry["preparation_seconds"] += details["preparation_seconds"]
                telemetry["hash_seconds"] += details["hash_seconds"]
                if not details["applied"]:
                    late_reason = details["skip_reason"]
                else:
                    prepared[sample_id] = converted[sample_id]
                release_started = time.perf_counter()
                del target, converted
                stream["release_seconds"] += time.perf_counter() - release_started
                if late_reason is not None:
                    break
            if late_reason is None:
                finalization_started = time.perf_counter()
                sentinel = object()
                if next(iterator, sentinel) is not sentinel:
                    raise TrainingJobValidationError("streamed target selection contains extra rows")
                stream["iterator_finalization_seconds"] += time.perf_counter() - finalization_started
        finally:
            finalization_started = time.perf_counter()
            iterator.close()
            stream["iterator_finalization_seconds"] += time.perf_counter() - finalization_started
        if late_reason is None and not reduction._native_classes_unchanged():
            late_reason = "native_class_contract_changed"
        if late_reason is not None:
            release_started = time.perf_counter()
            prepared.clear()
            stream["release_seconds"] += time.perf_counter() - release_started
            targets, telemetry = fallback(late_reason)
        else:
            telemetry["prepared_target_count"] = len(prepared)
            targets = MappingProxyType(prepared)
    # Sum disjoint hydration scopes; reduction/hash/release are separately timed.
    # GC is restored and collected after each scope, before any conversion.
    gc_result = dict(observations[0])
    last = observations[-1]
    for key in ("hydrate_seconds", "collection_seconds", "total_seconds"):
        gc_result[key] = sum(item[key] for item in observations)
    gc_result.update(
        gc_enabled_after=last["gc_enabled_after"], gc_threshold_after=last["gc_threshold_after"],
        gc_stats_after=last["gc_stats_after"], streamed_operation_count=len(observations),
        explicit_collection_performed=any(item["explicit_collection_performed"] for item in observations),
        explicit_collection_count=sum(item["explicit_collection_performed"] for item in observations),
        applied=any(item["applied"] for item in observations),
        all_streamed_operations_deferred=all(item["applied"] for item in observations),
        streamed_skip_reasons=[item["skip_reason"] for item in observations],
        gc_stats_scope="first hydration start through last hydration end, including intervening unpaused reduction")
    gc_result["gc_stats_delta"] = [
        {key: after[key] - before[key] for key in after}
        for before, after in zip(gc_result["gc_stats_before"], gc_result["gc_stats_after"])]
    stream["decoded_target_count"] = (stream["validation_pass_targets"]
                                      + stream["conversion_pass_targets"]
                                      + stream["fallback_hydrated_targets"])
    stream["total_seconds"] = time.perf_counter() - started
    telemetry["streaming"] = stream
    telemetry["release_seconds"] = stream["release_seconds"]
    return targets, gc_result, telemetry


def verify_corpus_job_inputs(spec: TrainingJobSpec) -> dict[str, Any]:
    """Validate immutable source spans and the exact ordered batch membership.

    These identities concern input provenance. They do not establish frontend
    qualification, corpus completeness, held-out generalization, or an admit.
    """
    with ExitStack() as resources:
        summary, _ = _verify_corpus_job_inputs(spec, resources)
        return summary


def _verify_corpus_job_inputs(spec: TrainingJobSpec, resources: ExitStack) -> tuple[dict[str, Any], Any]:
    """Keep verified runtime input views alive only in the supplied resource scope."""
    mapped_inputs = None
    if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
        from .autoencoder_campaign_job_inputs import verify_campaign_job_inputs
        return verify_campaign_job_inputs(spec), None
    if spec.corpus_manifest_artifact is None:
        return ({"verification_mode": "legacy_unverified", "dataset_and_split_identity_verified": False,
                 "frontend": "legacy_us_code", "global_holdout_verified": False}, None)
    from .autoencoder_corpus_manifest import load_corpus_manifest

    artifact = spec.corpus_manifest_artifact
    manifest = load_corpus_manifest(artifact.path, expected_sha256=artifact.sha256,
                                    expected_size_bytes=artifact.bytes)
    references = {item.sha256: item for item in spec.corpus_source_artifacts}
    expected = {(ref["sha256"], ref["bytes"]) for ref in manifest.source_refs}
    supplied = {(ref.sha256, ref.bytes) for ref in spec.corpus_source_artifacts}
    if supplied != expected:
        raise TrainingJobValidationError("corpus source artifacts differ from the exact manifest closure")

    def resolver(reference: Mapping[str, Any]) -> Path:
        bound = references.get(reference["sha256"])
        if bound is None or bound.bytes != reference["bytes"]:
            raise TrainingJobValidationError("corpus source is missing from the job binding")
        return Path(bound.path)

    source_summary = manifest.validate_sources(resolver)
    membership = manifest.verify_job_records(
        spec.samples, spec.validation_samples,
        dataset_snapshot_id=spec.dataset_snapshot_id, split_snapshot_id=spec.split_snapshot_id)
    if set(manifest.language_counts) != {spec.variant.source_language}:
        raise TrainingJobValidationError("corpus source languages differ from the qualified model frontend")
    if manifest.mode == "corpus" and set(manifest.source_kind_counts) != {"us_code"}:
        raise TrainingJobValidationError("corpus training requires the qualified us_code frontend")
    if spec.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION} and manifest.mode != "corpus":
        raise TrainingJobValidationError("v6 requires corpus mode with the qualified English us_code frontend")
    result = {**membership, "verification_mode": "manifest_and_source_bytes",
              "dataset_and_split_identity_verified": True,
              "source_validation": source_summary, "frontend": "legacy_us_code",
              "global_holdout_verified": False}
    if spec.schema_version in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        from .autoencoder_corpus_index import load_corpus_index

        artifact = spec.corpus_index_artifact
        index = load_corpus_index(artifact.path, expected_sha256=artifact.sha256,
                                  expected_size_bytes=artifact.bytes)
        if index.scope.selection_sha256 != spec.corpus_selection_sha256:
            raise TrainingJobValidationError("corpus index selection differs from the exact job scope binding")
        index_summary = index.verify_batch(manifest)
        result.update(verification_mode="manifest_source_bytes_and_frozen_index",
                      corpus_index_verification=index_summary,
                      corpus_index_membership_verified=True)
    if spec.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        from .autoencoder_embedding_production import load_embedding_production_receipt

        artifact = spec.embedding_production_artifact
        production = load_embedding_production_receipt(
            artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes)
        if production.native_execution_profile is not True:
            raise TrainingJobValidationError("v6 requires a native embedding production profile")
        if any(record.embedding_provenance is None
               or record.embedding_provenance.artifact_sha256 != artifact.sha256
               for record in manifest.records):
            raise TrainingJobValidationError("every corpus record must bind the exact embedding production receipt SHA-256")
        # A producer receipt may cover multiple batches. The job grants access
        # only to this manifest's source closure; each selected input, vector,
        # and provenance must match the receipt exactly. This checks integrity
        # and a declared execution profile, not authenticated model execution.
        production_summary = production.verify_records(manifest.records, resolver=resolver)
        result.update(verification_mode="manifest_source_bytes_frozen_index_and_embedding_production",
                      embedding_production_verified=True,
                      embedding_production_verification=production_summary)
    if spec.schema_version == ARROW_INPUT_SCHEMA_VERSION:
        from .autoencoder_arrow_inputs import load_embedding_inputs_ipc

        artifact = spec.arrow_embedding_inputs_artifact
        mapped_inputs = load_embedding_inputs_ipc(
            artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes,
            production=production, records=manifest.records, resolver=resolver)
        resources.callback(mapped_inputs.close)
        result.update(arrow_embedding_inputs_verified=True,
                      arrow_embedding_inputs_verification=mapped_inputs.verification_summary(),
                      arrow_embedding_inputs_initial_statistics=dict(mapped_inputs.statistics))
    return result, mapped_inputs


def _execute(spec: TrainingJobSpec, trainer: Callable[..., Mapping[str, Any]] | None,
             job_file_sha256: str | None, resources: ExitStack, *,
             defer_target_hydration_gc: bool = False,
             reduce_native_targets: bool = False,
             reviewed_runtime: ReviewedDecoderRuntime | None = None) -> dict[str, Any]:
    global _PROCESS_SOURCE_HASHES
    if type(spec) in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec):
        if trainer is not None or defer_target_hydration_gc or reduce_native_targets:
            raise TrainingJobValidationError("legacy trainer/hydration flags cannot select complete reviewed decoder execution")
        return _execute_reviewed_decoder_job(spec, reviewed_runtime, job_file_sha256)
    if reviewed_runtime is not None:
        raise TrainingJobValidationError("reviewed runtime requires the explicit complete-target job profile")
    started = time.perf_counter()
    tree_paths = _require_tree_pin()
    from . import legal_samples
    from .legal_samples import build_us_code_sample
    from . import modal_autoencoder
    from .modal_autoencoder import (
        MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS,
        AdaptiveModalAutoencoder, ModalAutoencoderTrainingState,
    )
    prepare_native_targets = None
    reduction_initialization_seconds = 0.0
    if reduce_native_targets:
        initialization_started = time.perf_counter()
        # Capture native class/method identities before hydration or training.
        from ._autoencoder_prepared_targets import _prepare_native_targets
        prepare_native_targets = _prepare_native_targets
        reduction_initialization_seconds = time.perf_counter() - initialization_started
    root = Path(__file__).resolve().parents[3]
    for name, module in (("autoencoder", modal_autoencoder), ("samples", legal_samples)):
        path = Path(module.__file__).resolve()
        if not path.is_file() or root not in path.parents:
            raise TrainingJobValidationError(f"{name} resolved outside the workspace tree: {path}")
        tree_paths[name] = str(path)
    tree_paths["worker"] = str(Path(__file__).resolve())
    tree_hashes = {name: _digest(Path(path).read_bytes()) for name, path in tree_paths.items()}
    if spec.expected_source_sha256 and dict(spec.expected_source_sha256) != tree_hashes:
        raise TrainingJobValidationError("source manifest SHA-256 mismatch")
    if _PROCESS_SOURCE_HASHES is not None and _PROCESS_SOURCE_HASHES != tree_hashes:
        raise TrainingJobValidationError("source files changed since this process's first job; start a fresh worker process")
    _PROCESS_SOURCE_HASHES = dict(tree_hashes)
    with modal_autoencoder._LEGAL_IR_TARGET_CACHE_LOCK:
        process_target_cache_initial_entries = len(modal_autoencoder._LEGAL_IR_TARGET_CACHE)

    corpus_verification_started = time.perf_counter()
    corpus_verification, mapped_inputs = _verify_corpus_job_inputs(spec, resources)
    corpus_verification_seconds = time.perf_counter() - corpus_verification_started

    base_load_started = time.perf_counter()
    base_materialized_checkpoint = {"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes}
    base_checkpoint_chain_depth = 0
    base_checkpoint_replayed_patch_bytes = 0
    state = None
    if spec.base_checkpoint_dependencies:
        from .modal_autoencoder_sparse_checkpoint import ResolutionLimits, artifact_ref, resolve_checkpoint
        supplied = (spec.base_checkpoint, *spec.base_checkpoint_dependencies)
        references = {item.sha256: item for item in supplied}

        def resolve_base_reference(reference):
            # Manifest content supplies hashes and lengths only. The job is
            # the complete authority for filesystem paths, staged by the owner.
            descriptor = references.get(reference["sha256"])
            if descriptor is None or descriptor.bytes != reference["bytes"]:
                raise TrainingJobValidationError("base checkpoint dependency is missing or has a mismatched size")
            return Path(descriptor.path)

        resolved_base = resolve_checkpoint(
            artifact_ref(spec.base_checkpoint), resolver=resolve_base_reference,
            limits=ResolutionLimits(max_artifacts=MAX_BASE_DEPENDENCIES + 1),
        )
        if {item["sha256"] for item in resolved_base.artifacts} != set(references):
            raise TrainingJobValidationError("base checkpoint dependencies contain unreferenced artifacts")
        state = resolved_base.state
        if resolved_base.manifest is not None:
            base_materialized_checkpoint = dict(resolved_base.materialized_checkpoint)
        base_checkpoint_chain_depth = resolved_base.depth
        base_checkpoint_replayed_patch_bytes = resolved_base.total_patch_bytes
        state_data = state.to_dict() if spec.arrow_feature_weights_artifact is not None else None
        # The resolution receipt must not retain the private JSON state after
        # an Arrow-backed replacement is constructed below.
        del resolved_base
    else:
        # Parse exactly the checked bytes. Legacy full-checkpoint jobs retain
        # their loading behavior and never enable delta-log recovery/truncation.
        with Path(spec.base_checkpoint.path).open("rb") as handle:
            raw = handle.read(spec.base_checkpoint.bytes + 1)
        if len(raw) != spec.base_checkpoint.bytes or _digest(raw) != spec.base_checkpoint.sha256:
            raise TrainingJobValidationError("base checkpoint size or SHA-256 mismatch")
        state_data = _parse_json(raw)
        if not isinstance(state_data, dict):
            raise TrainingJobValidationError("base checkpoint must contain a JSON object")
        del raw
    base_checkpoint_load_seconds = time.perf_counter() - base_load_started
    mapped_weights = None
    weight_load_started = time.perf_counter()
    if spec.arrow_feature_weights_artifact is not None:
        from .modal_autoencoder_arrow_weights import load_feature_embedding_weights_ipc
        artifact = spec.arrow_feature_weights_artifact
        mapped_weights = load_feature_embedding_weights_ipc(
            artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes,
            expected_base_checkpoint_sha256=base_materialized_checkpoint["sha256"],
        )
        resources.callback(mapped_weights.close)
    if state is None or mapped_weights is not None:
        state = ModalAutoencoderTrainingState.from_dict(state_data, feature_embedding_weights_override=mapped_weights)
    if mapped_weights is not None:
        # Tracking binds an independent overlay to the same immutable mapping.
        # Observe the model's bound container, not the unbound loader facade.
        mapped_weights = state.feature_embedding_weights
    unknown_state_fields = (
        set(state_data) - MODAL_AUTOENCODER_STATE_SERIALIZED_FIELDS
        if state_data is not None else set()
    )
    if unknown_state_fields:
        raise TrainingJobValidationError(f"unsupported checkpoint fields: {sorted(unknown_state_fields)}")
    del state_data
    weight_load_seconds = time.perf_counter() - weight_load_started
    base_identity = state.state_identity_record().to_dict()
    constructor = _effective_constructor_config(AdaptiveModalAutoencoder, spec.autoencoder_config)
    model = AdaptiveModalAutoencoder(state=state, **constructor)
    effective_constructor = dict(constructor)
    for name in constructor:
        if name == "compute_device":
            continue
        if hasattr(model, name):
            effective_constructor[name] = _thaw(_freeze(getattr(model, name)))
    sample_build_started = time.perf_counter()
    if mapped_inputs is None:
        samples = [build_us_code_sample(**asdict(row)) for row in spec.samples]
        validation = [build_us_code_sample(**asdict(row)) for row in spec.validation_samples]
    else:
        def mapped_samples(rows, record_ids):
            # JSON job rows retain their historical immutable representation.
            # Only the verified runtime sample receives the mapped vector; never
            # pass that view through SampleRecord, tuple(), or dataclass asdict().
            return [build_us_code_sample(
                title=row.title, section=row.section, text=row.text, citation=row.citation,
                embedding_model=row.embedding_model, embedding_vector=mapped_inputs.row(record_id))
                    for row, record_id in zip(rows, record_ids)]

        samples = mapped_samples(spec.samples, corpus_verification["training_record_ids"])
        validation = mapped_samples(spec.validation_samples, corpus_verification["validation_record_ids"])
    sample_build_seconds = time.perf_counter() - sample_build_started
    input_statistics_after_samples = dict(mapped_inputs.statistics) if mapped_inputs is not None else None
    train_ids = [sample.sample_id for sample in samples]
    validation_ids = [sample.sample_id for sample in validation]
    if len(set(train_ids)) != len(train_ids) or len(set(validation_ids)) != len(validation_ids):
        raise TrainingJobValidationError("duplicate sample identities within a split")
    overlap = sorted(set(train_ids) & set(validation_ids))
    train_texts = {_digest(sample.normalized_text.encode("utf-8")) for sample in samples}
    validation_texts = {_digest(sample.normalized_text.encode("utf-8")) for sample in validation}
    text_overlap = sorted(train_texts & validation_texts)
    if not validation or train_texts == validation_texts:
        validation_mode = "in_sample"
    else:
        validation_mode = "overlapping" if overlap or text_overlap else "holdout"
    target_load_started = time.perf_counter()
    shared_targets = None
    shared_target_supervision = None
    target_config = None
    target_snapshot = None
    shared_target_status_counts: dict[str, int] = {}
    shared_target_split_status_counts: dict[str, dict[str, int]] = {}
    target_snapshot_status_counts: dict[str, int] = {}
    target_artifact_format = None
    target_storage_statistics = None
    target_artifact_verification_seconds = 0.0
    target_hydration_seconds = 0.0
    target_hydration_gc = None
    target_snapshot_sample_count = 0
    streamed_reduction = None
    streamed_memory_before = None
    streamed_memory_after = None
    if spec.target_snapshot_artifact is not None:
        from .autoencoder_target_preparation import target_snapshot_config, unique_training_samples
        from .legal_ir_target_bundle import DEFAULT_MAX_BYTES, load_target_artifact
        artifact = spec.target_snapshot_artifact
        if artifact.bytes > DEFAULT_MAX_BYTES:
            raise TrainingJobValidationError("target artifact exceeds worker byte bound")
        if Path(artifact.path).stat().st_size != artifact.bytes:
            raise TrainingJobValidationError("target snapshot size mismatch")
        target_config = target_snapshot_config(spec.training_config)
        members = unique_training_samples(samples, validation)
        target_verification_started = time.perf_counter()
        target_snapshot = load_target_artifact(
            artifact.path, expected_sha256=artifact.sha256,
            config=target_config, max_bytes=min(artifact.bytes, DEFAULT_MAX_BYTES),
            max_shard_bytes=spec.target_shard_max_bytes,
        )
        target_artifact_verification_seconds = time.perf_counter() - target_verification_started
        close_snapshot = getattr(target_snapshot, "close", None)
        if close_snapshot is not None:
            resources.callback(close_snapshot)
        if target_snapshot.snapshot_id != spec.target_snapshot_id:
            raise TrainingJobValidationError("target snapshot identity mismatch")
        target_snapshot_sample_count = target_snapshot.sample_count
        target_hydration_started = time.perf_counter()
        if reduce_native_targets and _target_reduction_skip_reason(target_snapshot, trainer) is None:
            streamed_memory_before = _memory_observation()
            prepare_targets = prepare_native_targets
            checked_feature_targets = set()
            if spec.training_config.projection_reconstruction_objective == "raw_decoder":
                from .autoencoder_feature_training import verify_feature_target_supervision
                def prepare_targets(targets):
                    verify_feature_target_supervision(targets, target_snapshot.statuses,
                        spec.training_config.legal_ir_bridge_names, sample_ids=list(targets))
                    checked_feature_targets.update(targets)
                    return prepare_native_targets(targets)
            shared_targets, target_hydration_gc, streamed_reduction = _stream_reduced_shared_targets(
                target_snapshot, members, target_config, defer_gc=defer_target_hydration_gc,
                prepare=prepare_targets)
            streamed_memory_after = _memory_observation()
            # Hash/conversion and release are outside the disjoint hydration
            # scopes. The encompassing target_load_seconds includes all work.
            target_hydration_seconds = target_hydration_gc["total_seconds"]
        else:
            shared_targets, target_hydration_gc = _hydrate_shared_targets(
                target_snapshot, members, target_config, defer_gc=defer_target_hydration_gc)
            target_hydration_seconds = time.perf_counter() - target_hydration_started
        target_storage_statistics = dict(getattr(target_snapshot, "statistics", {}))
        target_artifact_format = target_storage_statistics.get("artifact_format", "json")
        statuses = target_snapshot.statuses
        for status in statuses.values():
            target_snapshot_status_counts[status] = target_snapshot_status_counts.get(status, 0) + 1
        for sample_id in shared_targets:
            status = statuses[sample_id]
            shared_target_status_counts[status] = shared_target_status_counts.get(status, 0) + 1
        for split_name, split_samples in (("training", samples), ("validation", validation)):
            counts: dict[str, int] = {}
            for sample in split_samples:
                status = statuses[sample.sample_id]
                counts[status] = counts.get(status, 0) + 1
            shared_target_split_status_counts[split_name] = counts
        if spec.training_config.projection_reconstruction_objective == "raw_decoder":
            from .autoencoder_feature_training import verify_feature_target_supervision
            if streamed_reduction is not None:
                from .autoencoder_feature_training import _supervision_receipt
                if checked_feature_targets != {member.sample_id for member in members}:
                    raise TrainingJobValidationError("streamed feature supervision selection is incomplete")
                shared_target_supervision = _supervision_receipt(
                    checked_feature_targets, spec.training_config.legal_ir_bridge_names)
            else:
                shared_target_supervision = verify_feature_target_supervision(
                    shared_targets, statuses, spec.training_config.legal_ir_bridge_names,
                    sample_ids=[member.sample_id for member in members])
    target_reduction = {
        "policy": "worker_private_native_targets_v1", "requested": reduce_native_targets,
        "applied": False, "skip_reason": "not_requested",
        "original_target_count": len(shared_targets) if shared_targets is not None else 0,
        "prepared_target_count": 0, "preparation_seconds": 0.0, "hash_seconds": 0.0,
        "release_seconds": 0.0, "initialization_seconds": reduction_initialization_seconds,
        "total_seconds": reduction_initialization_seconds, "memory_before": None, "memory_after": None,
        "validation_authority": False,
    }
    if streamed_reduction is not None:
        target_reduction.update(streamed_reduction)
        stream = streamed_reduction["streaming"]
        target_reduction.update(
            memory_before=streamed_memory_before, memory_after=streamed_memory_after,
            memory_observation_scope="before first streamed validation and after final conversion/fallback",
            total_seconds=(reduction_initialization_seconds + stream["reduction_seconds"]
                           + stream["release_seconds"] + stream["iterator_finalization_seconds"]))
    elif reduce_native_targets:
        reduction_started = time.perf_counter()
        target_reduction["memory_before"] = _memory_observation()
        reason = _target_reduction_skip_reason(target_snapshot, trainer)
        target_reduction["skip_reason"] = reason
        if reason is None:
            prepared, preparation = prepare_native_targets(shared_targets)
            target_reduction.update(preparation)
            release_started = time.perf_counter()
            if preparation["applied"]:
                # No target references have crossed into the trainer or model.
                # TargetBundle retains descriptors/manifest, not these graphs.
                shared_targets = prepared
            del prepared
            target_reduction["release_seconds"] = time.perf_counter() - release_started
        target_reduction["memory_after"] = _memory_observation()
        target_reduction["total_seconds"] += time.perf_counter() - reduction_started
    target_load_seconds = time.perf_counter() - target_load_started
    memory_before_training = _memory_observation()
    arrow_statistics_before = dict(mapped_weights.statistics) if mapped_weights is not None else None
    output = Path(spec.output_directory)
    # Refuse reuse before calling the trainer. This also prevents writing into
    # the checkpoint directory or a prior failed attempt's artifact directory.
    output.mkdir(parents=False, exist_ok=False)
    training_kwargs = spec.training_config.projection_kwargs()
    if shared_targets is not None:
        training_kwargs["legal_ir_targets"] = shared_targets
    segments: list[dict[str, Any]] = []
    if spec.capture_sparse_patches:
        from .modal_autoencoder_patch_codec import encode_patch

        def accepted_patch_sink(patch, context):
            segment_raw = encode_patch(
                patch, base_state_identity=context["base_state_identity"],
                result_state_identity=context["result_state_identity"],
                base_version_id=spec.base_version_id, sequence=len(segments),
                provenance={"job_id": spec.job_id, "run_id": spec.run_id,
                            "job_spec_sha256": spec.canonical_sha256,
                            "commit_label": context.get("label", "")},
            )
            descriptor = _write_exclusive(output / f"accepted-{len(segments):06d}.patch.json", segment_raw)
            segments.append({**descriptor, "capture_context": dict(context)})

        training_kwargs["accepted_patch_sink"] = accepted_patch_sink
    effective_projection = {
        name: training_kwargs.get(name, parameter.default)
        for name, parameter in inspect.signature(model.train_generalizable_projection).parameters.items()
        if name not in {"samples", "validation_samples", "progress_callback", "projection_profiler",
                        "precomputed_holdout_evaluation", "precomputed_training_evaluation",
                        "legal_ir_targets", "accepted_patch_sink"}
    }
    from .autoencoder_ontology_observation import observe_ontology_captures

    train_started = time.perf_counter()
    if spec.training_config.profile_projection:
        from .projection_profiler import ProjectionProfiler
        training_kwargs["projection_profiler"] = ProjectionProfiler()
    with observe_ontology_captures(producer_identity={
        "scope": "worker job label; not a complete dependency or reuse attestation",
        "job_spec_sha256": spec.canonical_sha256,
        "target_snapshot_id": spec.target_snapshot_id,
    }) as ontology_observation:
        if trainer is None:
            from .autoencoder_paths import TRAINING_PATH, gated_projection_training
            report = gated_projection_training(model, samples, execution_mode=TRAINING_PATH,
                                               validation_samples=validation, **training_kwargs)
        else:
            report = trainer(model, samples, validation_samples=validation, **training_kwargs)
    training_seconds = time.perf_counter() - train_started
    ontology_capture_observation = ontology_observation.to_dict()
    memory_after_training = _memory_observation()
    arrow_statistics_after = dict(mapped_weights.statistics) if mapped_weights is not None else None
    # The native projection method determines optimizer acceptance. Persisting a
    # candidate or having positive target coverage cannot promote or admit it.
    report = _parse_json(_json_bytes(dict(report)))
    if spec.capture_sparse_patches and len(segments) != int(report.get("accepted_epochs", 0)):
        raise TrainingJobValidationError("accepted epoch count differs from captured sparse segments")
    candidate_serialization_started = time.perf_counter()
    if spec.candidate_storage == "sparse":
        from .modal_autoencoder_sparse_checkpoint import artifact_ref, checkpoint_identity, encode_manifest
        candidate_materialized_checkpoint = checkpoint_identity(model.state)
        candidate_raw = encode_manifest(
            parent=artifact_ref(spec.base_checkpoint), base_version_id=spec.base_version_id,
            patches=[artifact_ref(segment) for segment in segments],
            materialized_checkpoint=candidate_materialized_checkpoint,
            state_identity=model.state.state_identity(), result_revision=model.state.state_revision,
            provenance={"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256},
        )
        candidate = _write_exclusive(output / "candidate.manifest.json", candidate_raw)
    else:
        candidate_raw = (model.state.to_json() + "\n").encode("utf-8")
        candidate = _write_exclusive(output / "candidate.state.json", candidate_raw)
        candidate_materialized_checkpoint = {key: candidate[key] for key in ("sha256", "bytes")}
    candidate_serialization_seconds = time.perf_counter() - candidate_serialization_started
    receipt = {
        "schema_version": "autoencoder-training-worker-receipt-v1",
        "job_id": spec.job_id, "run_id": spec.run_id,
        "job_spec": spec.to_dict(), "job_spec_canonical_sha256": spec.canonical_sha256,
        "job_file_sha256": job_file_sha256,
        "base_checkpoint": asdict(spec.base_checkpoint), "base_version_id": spec.base_version_id,
        "base_state_identity": base_identity, "candidate": candidate,
        "candidate_state_identity": model.state.state_identity_record().to_dict(),
        "admitted": False, "promotion_performed": False,
        "optimizer_accepted_epochs": int(report.get("accepted_epochs", 0)),
        "execution_mode": "injected_test" if trainer is not None else "native_training",
        "execution_path": "training", "execution_gate_applied": trainer is None,
        "training_report": report, "training_seconds": training_seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "sample_count": len(samples), "validation_sample_count": len(validation),
        "target_snapshot_id": spec.target_snapshot_id,
        "target_snapshot_artifact": asdict(spec.target_snapshot_artifact) if spec.target_snapshot_artifact else None,
        "target_shard_max_bytes": spec.target_shard_max_bytes,
        "shared_targets_verified": shared_targets is not None,
        "shared_target_count": len(shared_targets) if shared_targets is not None else 0,
        "target_snapshot_sample_count": target_snapshot_sample_count,
        "target_snapshot_status_counts": target_snapshot_status_counts,
        "shared_target_status_counts": shared_target_status_counts,
        "shared_target_split_status_counts": shared_target_split_status_counts,
        "shared_timeout_fallback_count": shared_target_status_counts.get("timeout", 0),
        "shared_target_reuse": {
            "enabled": shared_targets is not None,
            "target_source": "verified_shared_artifact" if shared_targets is not None else "native_metric_target_path",
            "preparation_included_in_training_seconds": False if shared_targets is not None else None,
            "scope": "Complete verified targets supplied to every training/tuning evaluation; timeout fallbacks remain timeout observations, not successful conversions."
                if shared_targets is not None else "No shared artifact; target generation and process-cache reuse remain inside training.",
        },
        "target_load_seconds": target_load_seconds,
        "sample_build_seconds": sample_build_seconds,
        "pretraining_seconds": train_started - started,
        "target_artifact_format": target_artifact_format,
        "target_storage_statistics": target_storage_statistics,
        "target_artifact_verification_seconds": target_artifact_verification_seconds,
        "target_hydration_seconds": target_hydration_seconds,
        "target_hydration_gc": target_hydration_gc,
        "target_reduction": target_reduction,
        "shared_target_verification_scope": (
            "artifact bytes, manifest/config and requested training/validation targets; unrequested target semantics not decoded"
            if target_artifact_format == "bundle" else
            "complete JSON snapshot and requested training/validation targets"
            if shared_targets is not None else None
        ),
        "arrow_feature_weights_artifact": asdict(spec.arrow_feature_weights_artifact) if spec.arrow_feature_weights_artifact else None,
        "weight_storage": "arrow_cow_feature_embeddings" if mapped_weights is not None else "private_json",
        "weight_load_seconds_after_json_parse": weight_load_seconds,
        "memory_before_training": memory_before_training,
        "memory_after_training_before_serialization": memory_after_training,
        "arrow_feature_statistics_before_training": arrow_statistics_before,
        "arrow_feature_statistics_after_training": arrow_statistics_after,
        "validation_mode": validation_mode, "overlapping_sample_ids": overlap,
        "overlapping_normalized_text_sha256": text_overlap,
        "heldout_canary_qualified": False,
        "bridge_names": list(spec.training_config.legal_ir_bridge_names),
        "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": spec.training_config.legal_ir_parallel_workers,
        "metric_disk_cache": 0, "use_sample_memory": False,
        "cache_observation": ("verified shared targets; no cold target-generation claim; disk metric cache disabled"
                              if shared_targets is not None else
                              "disk metric cache disabled; process caches may warm within job"),
        "process_target_cache_initial_entries": process_target_cache_initial_entries,
        "process_cache_initially_empty": process_target_cache_initial_entries == 0,
        "profile_projection": spec.training_config.profile_projection,
        "ontology_capture_observation": ontology_capture_observation,
        "effective_autoencoder_config": effective_constructor,
        "effective_projection_config": effective_projection,
        "compute_backend": model.compute_backend_metadata(),
        "runtime": {"python": platform.python_version(), "pid": os.getpid(),
                    "native_pool": worker_runtime()},
        "tree_paths": tree_paths,
        "tree_file_sha256": tree_hashes,
        "worker_source_sha256": tree_hashes["worker"],
        "source_manifest_verified": bool(spec.expected_source_sha256),
        "source_verification_scope": "file hashes before/after job, pinned module origins, and unchanged files since first process job; modules loaded before first job are not bytecode-attested",
        "caller_identity_labels_verified": False,
        "corpus_manifest_artifact": asdict(spec.corpus_manifest_artifact) if spec.corpus_manifest_artifact else None,
        "corpus_source_artifacts": [asdict(item) for item in spec.corpus_source_artifacts],
        "corpus_verification": corpus_verification,
        "corpus_verification_seconds": corpus_verification_seconds,
        "dataset_and_split_identity_verified": corpus_verification["dataset_and_split_identity_verified"],
        "sample_records_sha256": _digest(_json_bytes({"training": spec.to_dict()["samples"], "validation": spec.to_dict()["validation_samples"]})),
        "row_patch_transport": (
            "accepted sparse segments and immutable manifest; complete candidate checkpoint not written"
            if spec.candidate_storage == "sparse" else
            "accepted sparse segments plus complete private JSON recovery anchor"
            if spec.capture_sparse_patches else "disabled; complete private JSON state"
        ),
        "capture_sparse_patches": spec.capture_sparse_patches,
        "sparse_patch_segments": segments,
        "sparse_patch_bytes": sum(segment["bytes"] for segment in segments),
    }
    if shared_target_supervision is not None:
        receipt["shared_target_supervision"] = shared_target_supervision
    if spec.training_config.projection_optimizer_mode in {"guarded_adaptive", "productive_adaptive"}:
        receipt["projection_optimizer_scope"] = "job_local_reset_per_training_call"
        receipt["optimizer_history_persisted"] = False
    if spec.schema_version in {CAMPAIGN_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, INDEXED_SCHEMA_VERSION, SCHEMA_VERSION, SPARSE_SCHEMA_VERSION}:
        receipt.update(
            candidate_storage=spec.candidate_storage,
            base_checkpoint_dependencies=[asdict(item) for item in spec.base_checkpoint_dependencies],
            base_materialized_checkpoint=base_materialized_checkpoint,
            candidate_materialized_checkpoint=candidate_materialized_checkpoint,
            base_checkpoint_load_seconds=base_checkpoint_load_seconds,
            base_checkpoint_chain_depth=base_checkpoint_chain_depth,
            base_checkpoint_replayed_patch_bytes=base_checkpoint_replayed_patch_bytes,
            candidate_serialization_seconds=candidate_serialization_seconds,
        )
    if spec.schema_version in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        receipt.update(corpus_index_artifact=asdict(spec.corpus_index_artifact),
                       corpus_selection_sha256=spec.corpus_selection_sha256,
                       corpus_index_membership_verified=corpus_verification["corpus_index_membership_verified"])
    if spec.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        receipt.update(embedding_production_artifact=asdict(spec.embedding_production_artifact),
                       embedding_production_verified=True,
                       embedding_production_verification=corpus_verification["embedding_production_verification"])
    if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
        receipt.update({name: asdict(getattr(spec, name)) for name in CAMPAIGN_ARTIFACT_FIELDS})
        receipt.update(embedding_receipt_artifacts=[asdict(ref) for ref in spec.embedding_receipt_artifacts],
                       source_campaign_verified=True, produced_record_projection_verified=True)
    if spec.schema_version == ARROW_INPUT_SCHEMA_VERSION:
        # Staged files must remain immutable while mapped. Rechecking catches
        # persistent drift; it does not attest against transient external writes.
        mapped_inputs.verify_unchanged()
        receipt.update(
            arrow_embedding_inputs_artifact=asdict(spec.arrow_embedding_inputs_artifact),
            arrow_embedding_inputs_verified=True,
            arrow_embedding_inputs_verification=corpus_verification["arrow_embedding_inputs_verification"],
            embedding_input_storage="arrow_mapped_float32",
            arrow_embedding_inputs_statistics_before_samples=corpus_verification["arrow_embedding_inputs_initial_statistics"],
            arrow_embedding_inputs_statistics_after_samples=input_statistics_after_samples,
            arrow_embedding_inputs_statistics_after_training=dict(mapped_inputs.statistics),
            sample_build_seconds=sample_build_seconds,
            sample_build_seconds_per_sample=sample_build_seconds / (len(samples) + len(validation)),
        )
    if target_config is not None and target_snapshot_config(spec.training_config) != target_config:
        raise TrainingJobValidationError("shared target producer changed while training")
    if any(_digest(Path(path).read_bytes()) != tree_hashes[name] for name, path in tree_paths.items()):
        raise TrainingJobValidationError("pinned source files changed while the job ran; candidate is unregistered")
    receipt = _parse_json(_json_bytes(receipt))
    _write_exclusive(output / "receipt.json", _json_bytes(receipt) + b"\n")
    descriptor = os.open(output, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return receipt


def execute_training_job(spec: TrainingJobSpec | ReviewedDecoderTrainingJobSpec, *,
                         trainer: Callable[..., Mapping[str, Any]] | None = None,
                         job_file_sha256: str | None = None,
                         reviewed_runtime: ReviewedDecoderRuntime | None = None) -> dict[str, Any]:
    """Run one private candidate job; ``trainer`` is a local test injection.

    Start concurrent jobs in independent processes. The model's existing
    optimizer owns its transactions; this adapter does not nest an outer one.
    """
    return _execute_training_job(spec, trainer=trainer, job_file_sha256=job_file_sha256,
                                 reviewed_runtime=reviewed_runtime)


def _execute_native_training_job_with_deferred_gc(spec: TrainingJobSpec) -> dict[str, Any]:
    """Private spawn-pool entry; eligibility is rechecked immediately at hydration."""
    return _execute_training_job(spec, trainer=None, job_file_sha256=None,
                                 defer_target_hydration_gc=True)


def _execute_native_training_job_with_reduced_targets(spec: TrainingJobSpec) -> dict[str, Any]:
    """Private spawn entry; reduction follows complete target verification."""
    return _execute_training_job(spec, trainer=None, job_file_sha256=None,
                                 reduce_native_targets=True)


def _execute_native_training_job_with_deferred_gc_and_reduced_targets(spec: TrainingJobSpec) -> dict[str, Any]:
    """Combine independent native hydration and target-retention policies."""
    return _execute_training_job(spec, trainer=None, job_file_sha256=None,
                                 defer_target_hydration_gc=True, reduce_native_targets=True)


def _execute_training_job(spec: TrainingJobSpec, *, trainer: Callable[..., Mapping[str, Any]] | None,
                          job_file_sha256: str | None,
                          defer_target_hydration_gc: bool = False,
                          reduce_native_targets: bool = False,
                          reviewed_runtime: ReviewedDecoderRuntime | None = None) -> dict[str, Any]:
    if type(spec) in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec):
        if trainer is not None or defer_target_hydration_gc or reduce_native_targets:
            raise TrainingJobValidationError("legacy trainer/hydration flags cannot select complete reviewed decoder execution")
        if type(reviewed_runtime) is not ReviewedDecoderRuntime:
            raise TrainingJobValidationError("explicit reviewed decoder runtime required before model work")
    elif reviewed_runtime is not None:
        raise TrainingJobValidationError("reviewed runtime requires the explicit complete-target job profile")
    if type(reduce_native_targets) is not bool:
        raise TrainingJobValidationError("reduce_native_targets must be boolean")
    if reduce_native_targets and trainer is not None:
        raise TrainingJobValidationError("target reduction requires the native spawned worker without an injected trainer")
    if not isinstance(spec, TrainingJobSpec) and type(spec) not in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec):
        raise TrainingJobValidationError("spec must be a TrainingJobSpec or explicit reviewed decoder spec")
    if not _JOB_LOCK.acquire(blocking=False):
        raise TrainingJobValidationError("only one training job may run per worker process")
    try:
        with ExitStack() as resources, _worker_environment():
            return _execute(spec, trainer, job_file_sha256, resources,
                            defer_target_hydration_gc=defer_target_hydration_gc,
                            reduce_native_targets=reduce_native_targets,
                            reviewed_runtime=reviewed_runtime)
    finally:
        _JOB_LOCK.release()


def execute_training_job_file(path: str | Path, expected_sha256: str, *,
                              trainer: Callable[..., Mapping[str, Any]] | None = None,
                              reviewed_runtime: ReviewedDecoderRuntime | None = None) -> dict[str, Any]:
    """Verify a job artifact and execute those same JSON bytes in this process."""
    raw = Path(path).read_bytes()
    if _digest(raw) != expected_sha256:
        raise TrainingJobValidationError("job file SHA-256 mismatch")
    spec = TrainingJobSpec.from_dict(_parse_json(raw))
    return execute_training_job(spec, trainer=trainer, job_file_sha256=expected_sha256,
                                reviewed_runtime=reviewed_runtime)


__all__ = ["ReviewedMixedDecoderTrainingJobSpec", "REVIEWED_MIXED_DECODER_SCHEMA_VERSION",
           "REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE", "REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA",
           "REVIEWED_MIXED_ADMISSION_PROFILE", "ReviewedDecoderTrainingJobSpec", "ReviewedDecoderRuntime", "REVIEWED_DECODER_SCHEMA_VERSION", "BRIDGE_NAMES", "CheckpointArtifact", "ModelVariant", "SampleRecord", "TrainingConfig",
           "TrainingJobSpec", "TrainingJobValidationError", "execute_training_job", "execute_training_job_file",
           "verify_corpus_job_inputs"]


MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES = 32 * 1024 * 1024


def _reviewed_tokenizer_implementation_file(path):
    """Derive an exact ordinary source/native file identity, never a label."""
    import stat
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise TrainingJobValidationError("ordinary actual tokenizer implementation file required")
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise TrainingJobValidationError("ordinary tokenizer implementation ancestry required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_CHECKPOINT_BYTES:
            raise TrainingJobValidationError("bounded single-link tokenizer implementation file required")
        digest, total = hashlib.sha256(), 0
        while piece := os.read(descriptor, 1024**2):
            total += len(piece)
            if total > before.st_size:
                raise TrainingJobValidationError("tokenizer implementation grew during hashing")
            digest.update(piece)
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
                              info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if total != before.st_size or stamp(before) != stamp(os.fstat(descriptor)) or stamp(before) != stamp(path.lstat()):
            raise TrainingJobValidationError("tokenizer implementation changed during hashing")
        return {"path": str(path), "bytes": total, "sha256": digest.hexdigest()}
    finally:
        os.close(descriptor)


def _reviewed_tokenizer_configuration(value, *, added_token_type=None):
    """Lossless typed config tree; unknown objects never become repr strings."""
    count = 0
    active = set()
    def visit(item, depth=0):
        nonlocal count
        count += 1
        if count > 1_000_000 or depth > 64:
            raise TrainingJobValidationError("tokenizer frontend configuration bound exceeded")
        kind = type(item)
        if item is None or kind in (str, int, bool):
            if kind is str:
                item.encode("utf-8")
            return {"type": "NoneType" if item is None else kind.__name__, "value": item}
        if kind is float:
            if not math.isfinite(item):
                raise TrainingJobValidationError("finite tokenizer frontend configuration required")
            return {"type": "float", "value": item}
        if added_token_type is not None and kind is added_token_type:
            fields = {name: getattr(item, name) for name in ("content", "single_word", "lstrip", "rstrip", "normalized", "special")}
            if type(fields["content"]) is not str or any(type(fields[key]) is not bool for key in fields if key != "content"):
                raise TrainingJobValidationError("complete actual AddedToken configuration required")
            return {"type": "tokenizers.AddedToken", "fields": fields}
        if kind not in (dict, list, tuple):
            raise TrainingJobValidationError("unsupported non-JSON tokenizer frontend configuration")
        identity = id(item)
        if identity in active:
            raise TrainingJobValidationError("cyclic tokenizer frontend configuration unsupported")
        active.add(identity)
        try:
            if kind is dict:
                if any(type(key) not in (str, int) for key in item):
                    raise TrainingJobValidationError("typed tokenizer config dictionary keys required")
                return {"type": "dict", "items": [[visit(key, depth + 1), visit(child, depth + 1)]
                                                    for key, child in item.items()]}
            return {"type": kind.__name__, "items": [visit(child, depth + 1) for child in item]}
        finally:
            active.remove(identity)
    return visit(value)


def _reviewed_tokenizer_method(method):
    """Bind actual Python function code/defaults, or a pinned native method."""
    import marshal
    function = getattr(method, "__func__", method)
    code = getattr(function, "__code__", None)
    identity = {"module": getattr(function, "__module__", type(function).__module__),
                "qualname": getattr(function, "__qualname__", getattr(function, "__name__", type(function).__qualname__)),
                "kind": "python_code" if code is not None else "native_method"}
    if code is not None:
        # Format 2 excludes runtime reference flags while code hashes itself.
        identity.update(code_sha256=_digest(marshal.dumps(code, 2)),
            defaults=_reviewed_tokenizer_configuration(getattr(function, "__defaults__", None)),
            keyword_defaults=_reviewed_tokenizer_configuration(getattr(function, "__kwdefaults__", None)),
            closure=_reviewed_tokenizer_configuration(tuple(cell.cell_contents for cell in (getattr(function, "__closure__", None) or ()))))
    return identity


_REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_RAW_BYTES = 16 * 1024 * 1024
_REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_ENTRIES = 2
_REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE = {}
_REVIEWED_TOKENIZER_BINDING_DERIVATION_LOCK = threading.RLock()


def _reviewed_tokenizer_binding_derivation(raw):
    """Cache only immutable derivations of already freshly serialized HF bytes."""
    eligible = type(raw) is bytes and len(raw) <= _REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_RAW_BYTES
    if eligible:
        with _REVIEWED_TOKENIZER_BINDING_DERIVATION_LOCK:
            cached = _REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE.get(raw)
            if cached is not None:
                _REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE.pop(raw)
                _REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE[raw] = cached
                return cached
    pipeline = _parse_json(raw)
    if pipeline["kind"] != "huggingface_fast":
        return None
    backend = pipeline["backend"]["serialization"]
    model = backend["model"]
    if type(model) is not dict or "vocab" not in model or type(model["vocab"]) not in (dict, list):
        raise TrainingJobValidationError("complete actual model vocabulary required for binding")
    vocabulary = {"model_type": model.get("type"), "vocab": model["vocab"],
                  "added_tokens": backend["added_tokens"]}
    derived = (pipeline["kind"], "reviewed-tokenizer:" + pipeline["kind"] + ":" +
        _digest(_json_bytes({"kind": pipeline["kind"], "implementation": pipeline["implementation"],
                            "transport": pipeline["transport"]})),
        "sha256:" + _digest(_json_bytes(vocabulary)), "sha256:" + _digest(raw))
    if eligible:
        with _REVIEWED_TOKENIZER_BINDING_DERIVATION_LOCK:
            _REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE[raw] = derived
            while len(_REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE) > _REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_ENTRIES:
                del _REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE[next(iter(_REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE))]
    return derived


class ReviewedPretrainedTokenizer:
    """Body-only transport with a complete actual-pipeline identity.

    Production uses an actual fast tokenizer's Rust backend directly. The
    backend serialization, live frontend configuration, method implementations
    and ordinary Python/native assets are retained without dropping vocabulary
    or normalization rules. This is not a claim about all loaded dependencies.
    Slow/opaque frontends are explicitly unsupported. Fixed-byte fixtures need
    a separate explicit opt-in and never attest production tokenizer assets.
    """

    def __init__(self, tokenizer, *, bos_token_id, eos_token_id, vocab_size,
                 allow_fictional_fixture=False):
        if (type(vocab_size) is not int or not 3 <= vocab_size <= 2**31 or
                any(type(value) is not int or not 0 <= value < vocab_size
                    for value in (bos_token_id, eos_token_id)) or bos_token_id == eos_token_id or
                type(allow_fictional_fixture) is not bool):
            raise TrainingJobValidationError("explicit tokenizer special IDs, vocabulary and fixture scope required")
        self.tokenizer = tokenizer
        self.bos_token_id, self.eos_token_id, self.vocab_size = bos_token_id, eos_token_id, vocab_size
        self.allow_fictional_fixture = allow_fictional_fixture
        if allow_fictional_fixture:
            if any(not callable(getattr(tokenizer, name, None)) for name in ("encode", "decode", "pipeline_serialization")):
                raise TrainingJobValidationError("explicit complete fixed-byte fixture pipeline required")
        else:
            self._fast_backend()

    def _fast_backend(self):
        # No model/tokenizer loader or network call exists here. These imports
        # validate an already loaded production object only on the real path.
        from transformers import PreTrainedTokenizerFast
        from tokenizers import Tokenizer
        if (not isinstance(self.tokenizer, PreTrainedTokenizerFast) or
                not type(self.tokenizer).__module__.startswith("transformers.") or
                getattr(self.tokenizer, "is_fast", None) is not True):
            raise TrainingJobValidationError("actual supported Hugging Face fast tokenizer required")
        backend = self.tokenizer.backend_tokenizer
        if type(backend) is not Tokenizer:
            raise TrainingJobValidationError("actual tokenizers.Tokenizer backend required")
        if backend.get_vocab_size(with_added_tokens=True) != self.vocab_size:
            raise TrainingJobValidationError("declared vocabulary must equal the full actual backend vocabulary")
        if getattr(backend, "encode_special_tokens", None) is not False:
            raise TrainingJobValidationError("split-special-token transport is unsupported")
        serialized = backend.to_str()
        if type(serialized) is not str or not 0 < len(serialized.encode("utf-8")) <= MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES:
            raise TrainingJobValidationError("complete actual backend exceeds pipeline serialization capacity")
        body = _parse_json(serialized)
        required = {"model", "normalizer", "pre_tokenizer", "added_tokens", "post_processor", "decoder", "truncation", "padding"}
        if (type(body) is not dict or not required <= set(body) or
                body["truncation"] is not None or body["padding"] is not None):
            raise TrainingJobValidationError("complete backend without truncation or padding required")
        return backend, body

    def encode(self, text):
        if self.allow_fictional_fixture:
            return self.tokenizer.encode(text, add_special_tokens=False, truncation=False)
        backend, _ = self._fast_backend()
        return backend.encode(text, add_special_tokens=False).ids

    def decode(self, token_ids):
        if self.allow_fictional_fixture:
            return self.tokenizer.decode(token_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
        backend, _ = self._fast_backend()
        return backend.decode(token_ids, skip_special_tokens=False)

    def pipeline_serialization(self):
        import sys
        if type(self) is not ReviewedPretrainedTokenizer or any(name in self.__dict__ for name in ("encode", "decode", "pipeline_serialization", "binding_metadata", "_fast_backend")):
            raise TrainingJobValidationError("exact unshadowed reviewed tokenizer wrapper required")
        descriptors = {}
        def module_file(module):
            path = getattr(module, "__file__", None)
            if type(path) is not str:
                raise TrainingJobValidationError("actual tokenizer module asset identity required")
            row = _reviewed_tokenizer_implementation_file(path)
            descriptors[row["path"]] = row
        module_file(sys.modules[__name__])
        fixed = {"encode": {"add_special_tokens": False, "truncation": False, "padding": False},
                 "decode": {"skip_special_tokens": False, "clean_up_tokenization_spaces": False}}
        methods = {name: _reviewed_tokenizer_method(getattr(self, name))
                   for name in ("encode", "decode", "pipeline_serialization", "binding_metadata", "_fast_backend")}
        if self.allow_fictional_fixture:
            raw = self.tokenizer.pipeline_serialization()
            if type(raw) is not bytes or not 0 < len(raw) <= MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES:
                raise TrainingJobValidationError("bounded canonical fixed-byte fixture pipeline bytes required")
            payload = _parse_json(raw)
            if (type(payload) is not dict or set(payload) != {"schema", "kind", "backend", "frontend", "implementation", "transport"} or
                    payload["schema"] != "reviewed-decoder-tokenizer-pipeline/v1" or
                    payload["kind"] != "fictional_fixed_byte" or _json_bytes(payload) != raw or
                    payload["transport"] != {"body_only": True, "truncation": False, "padding": False} or
                    type(payload["backend"]) is not dict or type(payload["frontend"]) is not dict or
                    type(payload["implementation"]) is not list):
                raise TrainingJobValidationError("complete explicit fictional fixed-byte pipeline required")
            for row in payload["implementation"]:
                if type(row) is not dict or set(row) != {"path", "bytes", "sha256"} or _reviewed_tokenizer_implementation_file(row["path"]) != row:
                    raise TrainingJobValidationError("actual fixed-byte fixture implementation bytes differ")
                descriptors[row["path"]] = row
            for name in ("encode", "decode", "pipeline_serialization"):
                function = getattr(self.tokenizer, name)
                module = sys.modules.get(getattr(getattr(function, "__func__", function), "__module__", ""))
                if module is None:
                    raise TrainingJobValidationError("actual fixed-byte fixture method module required")
                module_file(module)
            payload = {**payload, "frontend": {"fixture": payload["frontend"], "wrapper_options": fixed,
                "wrapper_special_ids": {"bos_token_id": self.bos_token_id, "eos_token_id": self.eos_token_id, "vocab_size": self.vocab_size},
                "wrapper_methods": methods, "delegate_methods": {name: _reviewed_tokenizer_method(getattr(self.tokenizer, name))
                    for name in ("encode", "decode", "pipeline_serialization")}},
                "implementation": [descriptors[key] for key in sorted(descriptors)]}
        else:
            from tokenizers import AddedToken
            import tokenizers
            import tokenizers.tokenizers as native_tokenizers
            backend, backend_json = self._fast_backend()
            module_file(tokenizers)
            module_file(native_tokenizers)
            for cls in type(self.tokenizer).__mro__:
                if cls is object:
                    continue
                module = sys.modules.get(cls.__module__)
                if module is None:
                    raise TrainingJobValidationError("actual fast tokenizer class module unavailable")
                module_file(module)
            options = {name: getattr(self.tokenizer, name) for name in (
                "init_kwargs", "special_tokens_map_extended", "added_tokens_decoder", "model_max_length",
                "padding_side", "truncation_side", "clean_up_tokenization_spaces", "split_special_tokens",
                "chat_template", "name_or_path") if hasattr(self.tokenizer, name)}
            for name in ("add_prefix_space", "legacy", "add_bos_token", "add_eos_token", "spaces_between_special_tokens"):
                if hasattr(self.tokenizer, name):
                    options[name] = getattr(self.tokenizer, name)
            if type(getattr(self.tokenizer, "__dict__", None)) is not dict or self.tokenizer.__dict__.get("_tokenizer") is not backend:
                raise TrainingJobValidationError("actual supported fast tokenizer instance configuration required")
            # Bind all Python instance settings, including options not listed
            # above. Only the actual backend object is replaced by its complete
            # serialization elsewhere; unknown opaque frontend state refuses.
            instance_options = {key: value for key, value in self.tokenizer.__dict__.items() if key != "_tokenizer"}
            complete_instance = _reviewed_tokenizer_configuration(instance_options, added_token_type=AddedToken)
            front_methods = {name: _reviewed_tokenizer_method(getattr(self.tokenizer, name)) for name in ("encode", "decode")}
            for name in ("encode", "decode"):
                method = getattr(self.tokenizer, name)
                module = sys.modules.get(getattr(getattr(method, "__func__", method), "__module__", ""))
                if module is None:
                    raise TrainingJobValidationError("actual frontend method module unavailable")
                module_file(module)
            payload = {"schema": "reviewed-decoder-tokenizer-pipeline/v1", "kind": "huggingface_fast",
                "backend": {"serialization": backend_json, "encode_special_tokens": backend.encode_special_tokens,
                            "tokenizers_version": tokenizers.__version__,
                            "native_methods": {name: _reviewed_tokenizer_method(getattr(backend, name)) for name in ("encode", "decode")}},
                "frontend": {"transport_path": "direct_actual_tokenizers_Rust_backend/v2",
                    "python_frontend_not_used_for_mapping": True,
                    "class": type(self.tokenizer).__module__ + "." + type(self.tokenizer).__qualname__,
                    "configuration": _reviewed_tokenizer_configuration(options, added_token_type=AddedToken),
                    "instance_configuration": complete_instance,
                    "fixed_options": fixed,
                    "wrapper_special_ids": {"bos_token_id": self.bos_token_id, "eos_token_id": self.eos_token_id, "vocab_size": self.vocab_size},
                    "wrapper_methods": methods, "frontend_methods": front_methods},
                "implementation": [descriptors[key] for key in sorted(descriptors)],
                "transport": {"body_only": True, "truncation": False, "padding": False}}
        result = _json_bytes(payload)
        if not 0 < len(result) <= MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES:
            raise TrainingJobValidationError("complete tokenizer pipeline exceeds explicit byte capacity")
        return result

    def binding_metadata(self):
        """P5-compatible metadata derived from the actual complete pipeline.

        The whole-pipeline configuration digest is deliberately not embedded
        inside the pipeline itself: its underlying inputs and this method's
        code are already bound there, avoiding a recursive self-hash.
        """
        raw = self.pipeline_serialization()
        derived = (None if self.allow_fictional_fixture else _reviewed_tokenizer_binding_derivation(raw))
        if derived is None:
            pipeline = _parse_json(raw)
            if pipeline["kind"] == "huggingface_fast":
                backend = pipeline["backend"]["serialization"]
                model = backend["model"]
                if type(model) is not dict or "vocab" not in model or type(model["vocab"]) not in (dict, list):
                    raise TrainingJobValidationError("complete actual model vocabulary required for binding")
                vocabulary = {"model_type": model.get("type"), "vocab": model["vocab"],
                              "added_tokens": backend["added_tokens"]}
            else:
                backend = pipeline["backend"]
                if (type(backend.get("byte_to_id")) is not list or len(backend["byte_to_id"]) != 256 or
                        len(set(backend["byte_to_id"])) != 256 or
                        any(type(value) is not int or not 0 <= value < self.vocab_size for value in backend["byte_to_id"])):
                    raise TrainingJobValidationError("complete fixed-byte vocabulary required for fixture binding")
                vocabulary = {"byte_to_id": backend["byte_to_id"], "added_tokens": backend.get("added_tokens", [])}
            metadata = {"tokenizer_id": "reviewed-tokenizer:" + pipeline["kind"] + ":" +
                    _digest(_json_bytes({"kind": pipeline["kind"], "implementation": pipeline["implementation"],
                                        "transport": pipeline["transport"]})),
                "vocabulary_sha256": "sha256:" + _digest(_json_bytes(vocabulary)),
                "configuration_sha256": "sha256:" + _digest(raw),
                "bos_token_id": self.bos_token_id, "eos_token_id": self.eos_token_id, "vocab_size": self.vocab_size}
        else:
            _, tokenizer_id, vocabulary_sha256, configuration_sha256 = derived
            metadata = {"tokenizer_id": tokenizer_id, "vocabulary_sha256": vocabulary_sha256,
                        "configuration_sha256": configuration_sha256,
                        "bos_token_id": self.bos_token_id, "eos_token_id": self.eos_token_id, "vocab_size": self.vocab_size}
        if self.pipeline_serialization() != raw:
            raise TrainingJobValidationError("tokenizer pipeline changed during binding derivation")
        return metadata


# Low-level DATA transport only: no TRAIN/example, context-policy, legal-use,
# model-asset or execution permission follows from these profile names.
REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE = "reviewed-source-with-training-context/v1"
REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE = "reviewed-source-with-shared-training-context/v1"
REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2 = "reviewed-source-with-shared-training-context/v2"
REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3 = "reviewed-source-with-shared-training-context/v3"
REVIEWED_GENERATION_CONTEXT_PROFILE = "reviewed-decoder-training-context/v1"
REVIEWED_GENERATION_CONTEXT_MAX_RECORDS = 32
REVIEWED_GENERATION_CONTEXT_MAX_BYTES = 16 * 1024
REVIEWED_GENERATION_CONTEXT_MAX_TOKENS = 4096  # Includes its own BOS/EOS; no extra full-source allowance.
REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE = "qwen2-full-context-8192/v1"
REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE = "qwen2-chatml-field-layouts/v1"
_REVIEWED_QWEN2_CHATML_PROFILES = frozenset({"qwen2-chatml-complete-legal-ir/v1", REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE})
REVIEWED_QWEN2_CONTEXT_MAX_TOKENS = 8192
REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE = "qwen2-full-context-16384/v1"
REVIEWED_QWEN2_EXPANDED_CONTEXT_MAX_TOKENS = 16384


def _reviewed_generation_context_wire(source, query_identifiers):
    from ...logic.autoformal.training_cycle_inputs import _reviewed_wire
    # This validates transport, never review/exposure/context policy.
    # Complete TRAIN canonical_ir values are permitted DATA here;
    # only an admitted caller may decide that a model can use them.
    if set(source) != {"profile", "source_text", "governing_context",
                       "source_binding", "selection_context", "context"}:
        raise TrainingJobValidationError("closed six-key context generation source required")
    context = source["context"]
    shorttag = source.get("profile") == REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2
    keylayout = source.get("profile") == REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3
    shared = keylayout or shorttag or source.get("profile") == REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE
    if shared:
        # Explicit opt-in DATA transport. The codec bounds canonical expansion
        # before allocation; all record/leakage checks below use expanded data.
        # This profile grants no admission, context-use or execution authority.
        from ...logic.autoformal.training_cycle_inputs import unpack_reviewed_context_json_v1, unpack_reviewed_context_json_v2, unpack_reviewed_context_json_v3
        try:
            expanded = (unpack_reviewed_context_json_v3(context) if keylayout else
                        unpack_reviewed_context_json_v2(context) if shorttag
                        else unpack_reviewed_context_json_v1(context))
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise TrainingJobValidationError("bounded canonical shared context DATA required") from error
        if type(expanded) is not dict or set(expanded) != {"permitted", "retrieved"}:
            raise TrainingJobValidationError("closed shared permitted/retrieved context required")
        context = {"profile": REVIEWED_GENERATION_CONTEXT_PROFILE,
                   "mode": "rich_full_ast", **expanded}
    if (type(context) is not dict or set(context) != {"profile", "mode", "permitted", "retrieved"}
            or context["profile"] != REVIEWED_GENERATION_CONTEXT_PROFILE
            or type(context["mode"]) is not str or context["mode"] not in {"compact_profile", "rich_full_ast"}
            or type(context["permitted"]) is not list or type(context["retrieved"]) is not list):
        raise TrainingJobValidationError("closed explicit context DATA profile required")
    records = context["permitted"] + context["retrieved"]
    if not 1 <= len(records) <= REVIEWED_GENERATION_CONTEXT_MAX_RECORDS:
        raise TrainingJobValidationError("bounded nonempty complete context records required")
    try:
        # Existing ordinary-JSON owner checks finite values, UTF8,
        # string keys, depth/node bounds, and refuses custom objects.
        _reviewed_wire(source)
        raw = _reviewed_wire(source["context"] if shared else context)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise TrainingJobValidationError("ordinary finite UTF8 context JSON required") from error
    if len(raw) > REVIEWED_GENERATION_CONTEXT_MAX_BYTES:
        raise TrainingJobValidationError("complete context exceeds fixed byte sub-bound; truncation forbidden")
    identifiers = set()
    forbidden = {"query_target", "query_canonical_ir", "target_json", "target_token_ids",
                 "decoder_input_ids", "labels", "gold_target", "teacher_forced_prefix"}
    def screen(value):
        if type(value) is dict:
            if forbidden.intersection(value):
                raise TrainingJobValidationError("query target or decoder-prefix field in context DATA")
            for key, child in value.items():
                screen(key)
                screen(child)
        elif type(value) is list:
            for child in value:
                screen(child)
        elif type(value) is str and value in query_identifiers:
            raise TrainingJobValidationError("query row or unit ID in context DATA")
    for record in records:
        if (type(record) is not dict or set(record) != {"id", "content"}
                or type(record["id"]) is not str or not 0 < len(record["id"]) <= 512
                or any(c in record["id"] for c in "\r\n\0")
                or record["id"] in identifiers or record["id"] in query_identifiers
                or type(record["content"]) is not dict or not record["content"]):
            raise TrainingJobValidationError("unique non-query closed context id/content records required")
        identifiers.add(record["id"])
        screen(record["content"])
    return raw.decode("utf-8")


def _reviewed_builtin_gpt2_causal_buffers(model, *, initialize=False):
    """Check only the exact built-in GPT2 constructor's deterministic buffers.

    Older built-in GPT2 attention registers a boolean causal triangle and a
    float32 -1e4 scalar as nonpersistent. They are absent from state_dict and
    to_empty destroys their constructor values. Derive the registration shape
    from the installed exact attention constructor on meta, then check its
    known recipe independently. Unknown nonpersistent state remains refused.
    """
    import torch
    from transformers import GPT2Config, GPT2LMHeadModel
    from transformers.models.gpt2.modeling_gpt2 import GPT2Attention
    if type(model) is not GPT2LMHeadModel or type(model.config) is not GPT2Config:
        raise TrainingJobValidationError("exact built-in GPT2 model/config required for causal buffer reconstruction")
    config = model.config
    positions, layers = config.n_positions, config.n_layer
    # The injected backend accepts an already owned model, including zero
    # attention layers and contexts above the local loader's resource profile.
    # Loader allocation limits belong to its preflight, not this state check.
    if (type(positions) is not int or positions < 1 or
            type(layers) is not int or layers < 0):
        raise TrainingJobValidationError("valid built-in GPT2 dimensions required for causal buffer validation")
    # No CPU parameter/mask storage or RNG change is permitted for this
    # constructor-topology witness, including on constructor failure.
    with torch.random.fork_rng(devices=[]):
        with torch.device("meta"):
            reference = GPT2Attention(config, layer_idx=0)
    expected = set(reference._non_persistent_buffers_set)
    if expected not in (set(), {"bias", "masked_bias"}):
        raise TrainingJobValidationError("unsupported built-in GPT2 nonpersistent buffer constructor")
    descriptors = {"bias": ((1, 1, positions, positions), torch.bool),
                   "masked_bias": ((), torch.float32)}
    for name in expected:
        value = reference._buffers.get(name)
        shape, dtype = descriptors[name]
        if not torch.is_tensor(value) or tuple(value.shape) != shape or value.dtype != dtype or value.device.type != "meta":
            raise TrainingJobValidationError("built-in GPT2 causal buffer constructor schema differs")
    attention_names = {"transformer.h." + str(index) + ".attn" for index in range(layers)}
    if config.add_cross_attention:
        attention_names.update("transformer.h." + str(index) + ".crossattention" for index in range(layers))
    modules = dict(model.named_modules())
    if len(model.transformer.h) != layers or any(type(modules.get(name)) is not GPT2Attention for name in attention_names):
        raise TrainingJobValidationError("built-in GPT2 attention module topology differs")
    names = []
    for module_name, module in modules.items():
        registered = set(module._non_persistent_buffers_set)
        if registered != (expected if module_name in attention_names else set()):
            raise TrainingJobValidationError("unknown or missing local decoder nonpersistent buffers")
        for name in sorted(registered):
            value = module._buffers.get(name)
            shape, dtype = descriptors[name]
            if not torch.is_tensor(value) or tuple(value.shape) != shape or value.dtype != dtype or value.device.type not in {"meta", "cpu", "cuda"}:
                raise TrainingJobValidationError("built-in GPT2 causal buffer schema differs")
            if initialize:
                if value.device.type != "cpu":
                    raise TrainingJobValidationError("causal buffer reconstruction requires bounded CPU materialization")
                with torch.no_grad():
                    if name == "bias":
                        value.fill_(True).tril_()
                    else:
                        value.fill_(-1e4)
            if value.device.type != "meta":
                if name == "masked_bias":
                    valid = value.item() == -1e4
                else:
                    # At most max(1 MiB, n_positions) boolean comparison
                    # scratch; never build a second full causal-mask tensor.
                    columns = torch.arange(positions, device=value.device)
                    rows_per_chunk = max(1, min(256, 1024**2 // positions))
                    valid = True
                    for start in range(0, positions, rows_per_chunk):
                        stop = min(positions, start + rows_per_chunk)
                        rows = torch.arange(start, stop, device=value.device)
                        if not torch.equal(value[0, 0, start:stop], rows[:, None] >= columns[None, :]):
                            valid = False
                            break
                if not valid:
                    raise TrainingJobValidationError("built-in GPT2 deterministic causal buffer values differ")
            names.append(module_name + "." + name)
    return sorted(names)


def _reviewed_builtin_default_rotary_parameters(config, *, _family):
    """Keep the two reviewed built-in default-RoPE configuration layouts closed."""
    import transformers
    legacy = transformers.__version__ == "4.52.1"
    if legacy:
        # This installed implementation reads these fields directly. Do not
        # invent newer config attributes or silently admit a scaling recipe.
        scaling = getattr(config, "rope_scaling", False)
        default_scaling = (scaling is None or
            type(scaling) is dict and (scaling == {"rope_type": "default"} or
                scaling == {"type": "default", "rope_type": "default"}))
        partial = getattr(config, "partial_rotary_factor", 1.0)
        if (hasattr(config, "rope_parameters") or not default_scaling or
                type(partial) not in (int, float) or partial != 1.0):
            raise TrainingJobValidationError("unsupported installed default rotary configuration")
        rope = {"rope_type": "default", "rope_theta": getattr(config, "rope_theta", None)}
        if _family == "qwen2" and (config.use_sliding_window is not False or hasattr(config, "layer_types")):
            raise TrainingJobValidationError("fixed full-attention legacy Qwen2 rotary recipe required")
    else:
        if not hasattr(config, "rope_parameters"):
            raise TrainingJobValidationError("unsupported installed rotary configuration version")
        rope = config.rope_parameters
        if _family == "qwen2" and (config.use_sliding_window is not False or
                config.layer_types != ["full_attention"] * config.num_hidden_layers):
            raise TrainingJobValidationError("fixed full-attention Qwen2 rotary recipe required")
    if (type(rope) is not dict or set(rope) != {"rope_type", "rope_theta"} or
            rope["rope_type"] != "default" or type(rope["rope_theta"]) not in (int, float) or
            not math.isfinite(rope["rope_theta"]) or rope["rope_theta"] <= 0):
        raise TrainingJobValidationError("fixed finite default Llama rotary recipe required")
    return rope, legacy


def _reviewed_builtin_llama_rotary_buffers(model, *, initialize=False, _family="llama"):
    """Validate/reconstruct the two deterministic default-RoPE tensor attributes.

    Newer built-ins register both tensors. Transformers 4.52.1 registers only
    inv_freq and keeps original_inv_freq as a plain tensor. Preserve that exact
    layout; neither checkpoint absence nor a plain attribute grants mutability.
    """
    import torch
    if _family == "llama":
        from transformers import LlamaConfig, LlamaForCausalLM
        from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding
    elif _family == "qwen2":
        from transformers import Qwen2Config as LlamaConfig, Qwen2ForCausalLM as LlamaForCausalLM
        from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding as LlamaRotaryEmbedding
    else:
        raise TrainingJobValidationError("closed built-in rotary family required")
    if type(model) is not LlamaForCausalLM or type(model.config) is not LlamaConfig:
        raise TrainingJobValidationError("exact built-in Llama model/config required")
    config = model.config
    dim = (getattr(config, "head_dim", None) or config.hidden_size // config.num_attention_heads) if _family == "qwen2" else config.head_dim
    positions = config.max_position_embeddings
    rope, legacy = _reviewed_builtin_default_rotary_parameters(config, _family=_family)
    if (type(dim) is not int or not 2 <= dim <= 65536 or dim % 2 or
            type(positions) is not int or not 1 <= positions <= 65536):
        raise TrainingJobValidationError("fixed finite default Llama rotary recipe required")
    with torch.random.fork_rng(devices=[]):
        with torch.device("meta"):
            reference = LlamaRotaryEmbedding(config)
    expected = {"inv_freq", "original_inv_freq"}
    registered_expected = {"inv_freq"} if legacy else expected
    if (set(reference._non_persistent_buffers_set) != registered_expected or
            set(reference._buffers) != registered_expected or reference.attention_scaling != 1.0 or
            legacy and "original_inv_freq" not in vars(reference)):
        raise TrainingJobValidationError("unsupported built-in Llama rotary constructor")
    modules = dict(model.named_modules())
    rotary = modules.get("model.rotary_emb")
    if (type(rotary) is not LlamaRotaryEmbedding or rotary.config is not config or
            rotary.rope_type != "default" or type(rotary.attention_scaling) is not float or
            rotary.attention_scaling != 1.0 or
            type(rotary.max_seq_len_cached) is not int or rotary.max_seq_len_cached != positions or
            type(rotary.original_max_seq_len) is not int or rotary.original_max_seq_len != positions):
        raise TrainingJobValidationError("built-in Llama rotary module recipe differs")
    names = []
    for module_name, module in modules.items():
        registered = set(module._non_persistent_buffers_set)
        if registered != (registered_expected if module_name == "model.rotary_emb" else set()):
            raise TrainingJobValidationError("unknown or missing Llama nonpersistent buffers")
        if module_name != "model.rotary_emb":
            continue
        if legacy and (set(module._buffers) != registered_expected or
                "original_inv_freq" not in vars(module)):
            raise TrainingJobValidationError("built-in Llama rotary tensor registration differs")
        for name in sorted(expected):
            value, witness = getattr(module, name, None), getattr(reference, name, None)
            if (not torch.is_tensor(value) or tuple(value.shape) != (dim // 2,) or
                    value.dtype != torch.float32 or value.device.type not in {"meta", "cpu", "cuda"} or
                    not torch.is_tensor(witness) or tuple(witness.shape) != (dim // 2,) or
                    witness.dtype != torch.float32 or witness.device.type != "meta"):
                raise TrainingJobValidationError("built-in Llama rotary buffer schema differs")
            # Module.to_empty moves registered buffers, leaving this installed
            # plain meta attribute behind. Reconstruct only this known recipe.
            if initialize and legacy and name == "original_inv_freq" and value.device.type == "meta":
                value = torch.empty((dim // 2,), dtype=torch.float32, device="cpu")
                setattr(module, name, value)
            if value.device.type != "meta":
                exact = 1.0 / (rope["rope_theta"] ** (torch.arange(0, dim, 2, dtype=torch.float32, device=value.device) / dim))
                if initialize:
                    if value.device.type != "cpu":
                        raise TrainingJobValidationError("local Llama reconstruction requires bounded CPU materialization")
                    with torch.no_grad():
                        value.copy_(exact)
                if not torch.equal(value, exact):
                    raise TrainingJobValidationError("built-in Llama deterministic rotary buffer values differ")
            elif initialize:
                raise TrainingJobValidationError("Llama rotary initialization requires materialized CPU buffers")
            names.append(module_name + "." + name)
    return sorted(names)


def _reviewed_builtin_qwen2_rotary_buffers(model, *, initialize=False):
    """The same independent default-RoPE witness, with exact Qwen2 types."""
    return _reviewed_builtin_llama_rotary_buffers(model, initialize=initialize, _family="qwen2")


def _reviewed_training_conditioning_profile(value, architecture, model_profile):
    if value is not None and (type(value) is not str or value not in (_REVIEWED_QWEN2_CHATML_PROFILES | {REVIEWED_DIGEST_OMITTED_CHATML_PROFILE})
            or architecture != "causal_lm" or model_profile != "builtin-qwen2-bfloat16/v1"):
        raise TrainingJobValidationError("explicit supported Qwen2 causal training conditioning profile required")
    return value


_EXPECTED_TEACHER_FORCED_COUNT_KEYS = (
    "expected_record_count", "expected_input_positions", "expected_raw_label_positions",
    "expected_raw_ignored_positions", "expected_target_body_eos_positions",
    "expected_aligned_nonignored_positions", "expected_aligned_ignored_positions",
)


def _expected_teacher_forced_position_counts(source_length, target_length, *,
                                            encoder_decoder, prompt_length=None):
    """Expected geometry from validated Python lists; not observed model scoring.

    Only expected_target_body_eos_positions excludes target BOS and includes
    EOS. expected_input_positions counts input_ids positions (encoder-side only
    for encoder-decoder), not all model compute. Raw label/ignored and input
    counts include context/BOS wherever present; aligned counts account for
    causal labels[1:]. No loss reduction, NLL or numerical execution is inferred.
    """
    scored = target_length - 1
    if encoder_decoder:
        inputs, labels, ignored, aligned_ignored = source_length, scored, 0, 0
    else:
        ignored = source_length + 1 if prompt_length is None else prompt_length
        inputs = labels = ignored + scored
        aligned_ignored = ignored - 1
    return dict(zip(_EXPECTED_TEACHER_FORCED_COUNT_KEYS,
                    (1, inputs, labels, ignored, scored, scored, aligned_ignored)))


class TorchReviewedDecoderBackend:
    """Normal teacher-forced Torch updates for an injected pretrained model.

    Model, optimizer and tokenizer are supplied by the admitted caller. This
    class never calls from_pretrained, downloads weights or grants resources.
    It supports one already-owned CPU or CUDA device; sharded/meta models are
    refused. Checkpoint state includes optimizer progress and CPU/device RNG.
    Exact resumption and physical assets remain matters for actual validation,
    rather than conclusions inferred from this interface or checkpoint bytes.
    """

    def __init__(self, model, optimizer, tokenizer, *, architecture,
                 max_sequence_tokens, pretrained, gradient_clip=1.0, model_profile=None, training_conditioning_profile=None, target_codec="complete-reviewed-norm-json/v2", cache_source_epoch_marker=None):
        if architecture not in {"encoder_decoder", "causal_lm"}:
            raise TrainingJobValidationError("explicit supported pretrained decoder architecture required")
        if type(max_sequence_tokens) is not int or not 3 <= max_sequence_tokens <= 262144:
            raise TrainingJobValidationError("explicit finite pretrained model context bound required")
        if type(pretrained) is not bool or type(gradient_clip) not in (int, float) or not math.isfinite(gradient_clip) or gradient_clip <= 0:
            raise TrainingJobValidationError("explicit pretrained declaration and finite gradient bound required")
        for value, methods in ((model, ("parameters", "named_parameters", "state_dict", "load_state_dict", "train", "get_input_embeddings", "get_output_embeddings", "named_buffers")),
                               (optimizer, ("zero_grad", "step", "state_dict", "load_state_dict"))):
            if any(not callable(getattr(value, name, None)) for name in methods):
                raise TrainingJobValidationError("injected Torch model/optimizer interface incomplete")
        if type(getattr(optimizer, "param_groups", None)) is not list:
            raise TrainingJobValidationError("injected Torch optimizer parameter groups required")
        if model_profile is not None and (type(model_profile) is not str or model_profile != "builtin-qwen2-bfloat16/v1"):
            raise TrainingJobValidationError("explicit supported Torch decoder model profile required")
        if type(target_codec) is not str or target_codec not in {"complete-reviewed-norm-json/v2", REVIEWED_DIGEST_OMITTED_TARGET_CODEC}:
            raise TrainingJobValidationError("explicit supported target codec required")
        if cache_source_epoch_marker is not None:
            if target_codec != REVIEWED_DIGEST_OMITTED_TARGET_CODEC or model_profile != "builtin-qwen2-bfloat16/v1" or architecture != "causal_lm":
                raise TrainingJobValidationError("cache marker requires the explicit same-digest Qwen profile")
            cache_source_epoch_marker = _reviewed_digest_cache_epoch_validate_marker(cache_source_epoch_marker)
        self.cache_source_epoch_marker = (_freeze(cache_source_epoch_marker) if cache_source_epoch_marker is not None else None)
        self.target_codec = target_codec
        self.training_conditioning_profile = _reviewed_training_conditioning_profile(
            training_conditioning_profile, architecture, model_profile)
        self.model_profile = model_profile
        self._assert_target_codec_profile()
        self.model, self.optimizer, self.tokenizer = model, optimizer, tokenizer
        self.architecture, self.max_sequence_tokens = architecture, max_sequence_tokens
        self.pretrained, self.gradient_clip = pretrained, float(gradient_clip)
        self._optimizer_steps = 0
        self._tokenizer_pipeline_contract_raw = None

    def _assert_target_codec_profile(self):
        if (type(self.target_codec) is not str or self.target_codec not in {
                "complete-reviewed-norm-json/v2", REVIEWED_DIGEST_OMITTED_TARGET_CODEC} or
                (self.training_conditioning_profile == REVIEWED_DIGEST_OMITTED_CHATML_PROFILE) !=
                (self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC and self.model_profile == "builtin-qwen2-bfloat16/v1")):
            raise TrainingJobValidationError("target codec and training conditioning profile differ")

    def _torch(self):
        import torch
        return torch

    def _checkpoint_byte_limit(self):
        if self.model_profile is None:
            return MAX_REVIEWED_DECODER_STATE_BYTES
        if (self.model_profile != "builtin-qwen2-bfloat16/v1" or
                type(self.model).__module__ != "transformers.models.qwen2.modeling_qwen2" or
                type(self.model).__qualname__ != "Qwen2ForCausalLM"):
            raise TrainingJobValidationError("exact explicitly profiled Qwen2 backend required")
        torch = self._torch()
        if any(p.device.type != "cpu" or p.dtype != torch.bfloat16 for p in self.model.parameters()):
            raise TrainingJobValidationError("Qwen2 profile requires CPU BF16 parameters")
        return 2 * 1024**3

    def _pipeline_contract(self):
        # Reuse the independently checked input-owner recipe. It derives the
        # complete pipeline identity and authenticates real implementation files.
        from ...logic.autoformal.training_cycle_inputs import (
            ReviewedDecoderInputValidationError, _reviewed_decoder_tokenizer_contract)
        try:
            contract = _reviewed_decoder_tokenizer_contract(self.tokenizer)
        except ReviewedDecoderInputValidationError as error:
            raise TrainingJobValidationError("tokenizer pipeline changed or unsupported") from error
        raw = _json_bytes(contract)
        if self._tokenizer_pipeline_contract_raw is None:
            self._tokenizer_pipeline_contract_raw = raw
        elif raw != self._tokenizer_pipeline_contract_raw:
            raise TrainingJobValidationError("tokenizer pipeline changed after decoder configuration")
        return contract

    def _assert_pipeline(self, expected):
        if self._pipeline_contract() != expected:
            raise TrainingJobValidationError("tokenizer pipeline changed during decoder callback")

    def _configuration(self):
        self._assert_target_codec_profile()
        training_profile = _reviewed_training_conditioning_profile(
            self.training_conditioning_profile, self.architecture, self.model_profile)
        contract = self._pipeline_contract()
        if type(self.tokenizer) is not ReviewedPretrainedTokenizer:
            raise TrainingJobValidationError("exact reviewed tokenizer transport required by Torch backend")
        binding = self.tokenizer.binding_metadata()
        if binding["configuration_sha256"] != "sha256:" + contract["pipeline_sha256"]:
            raise TrainingJobValidationError("tokenizer pipeline differs from independently derived binding")
        parameters = list(self.model.parameters())
        names = {id(value): name for name, value in self.model.named_parameters()}
        if not parameters or len({value.device for value in parameters}) != 1:
            raise TrainingJobValidationError("one owned model device and nonempty parameters required")
        device = parameters[0].device
        if any(value.device != device for _, value in self.model.named_buffers()):
            raise TrainingJobValidationError("all model buffers must share the owned model device")
        if device.type not in {"cpu", "cuda"}:
            raise TrainingJobValidationError("meta or unsupported pretrained model device")
        groups, seen = [], set()
        for group in self.optimizer.param_groups:
            ids = [id(value) for value in group["params"]]
            if any(value not in names or value in seen for value in ids) or len(ids) != len(set(ids)):
                raise TrainingJobValidationError("optimizer contains foreign or duplicate model parameters")
            seen.update(ids)
            groups.append({**{key: value for key, value in group.items() if key != "params"},
                           "parameter_names": [names[value] for value in ids]})
        if not {id(value) for value in parameters if value.requires_grad} <= seen or not any(value.requires_grad for value in parameters):
            raise TrainingJobValidationError("all trainable model parameters must belong to the optimizer")
        config = getattr(self.model, "config", None)
        model_config = config.to_dict() if callable(getattr(config, "to_dict", None)) else None
        if type(model_config) is not dict or type(getattr(config, "is_encoder_decoder", None)) is not bool:
            raise TrainingJobValidationError("explicit pretrained model configuration required")
        if (type(self.model).__module__ == "transformers.models.gpt2.modeling_gpt2"
                and type(self.model).__qualname__ == "GPT2LMHeadModel"):
            _reviewed_builtin_gpt2_causal_buffers(self.model)
        if (type(self.model).__module__ == "transformers.models.llama.modeling_llama"
                and type(self.model).__qualname__ == "LlamaForCausalLM"):
            _reviewed_builtin_llama_rotary_buffers(self.model)
        if self.model_profile is not None:
            self._checkpoint_byte_limit()
            _reviewed_builtin_qwen2_rotary_buffers(self.model)
            native, _ = self.tokenizer._fast_backend()
            token_domain = set(native.get_vocab(with_added_tokens=True).values())
            actual_vocab = contract["vocab_size"]
            model_vocab = model_config.get("vocab_size")
            if (token_domain != set(range(actual_vocab)) or type(model_vocab) is not int or
                    not actual_vocab <= model_vocab <= actual_vocab+4096 or
                    config.bos_token_id != self.tokenizer.bos_token_id or config.eos_token_id != self.tokenizer.eos_token_id or
                    any(embedding is None or embedding.weight.shape[0] != model_vocab for embedding in
                        (self.model.get_input_embeddings(), self.model.get_output_embeddings()))):
                raise TrainingJobValidationError("Qwen2 model vocabulary/special IDs differ from complete tokenizer domain")
        if config.is_encoder_decoder != (self.architecture == "encoder_decoder"):
            raise TrainingJobValidationError("pretrained architecture differs from model configuration")
        declared_limit = model_config.get("max_position_embeddings", model_config.get("n_positions"))
        if type(declared_limit) is int and self.max_sequence_tokens > declared_limit:
            raise TrainingJobValidationError("declared context exceeds the model position limit")
        configuration = {"schema": ("torch-digest-omitted-reviewed-decoder-configuration/v1" if self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC else "torch-complete-reviewed-decoder-configuration/v2"),
                "architecture": self.architecture, "max_sequence_tokens": self.max_sequence_tokens,
                "gradient_clip": self.gradient_clip, "pretrained_declaration": self.pretrained,
                "source_profile": "reviewed-source-selection-context/v2",
                "target_codec": self.target_codec, "semantic_selection_supported": False,
                "model_class": type(self.model).__module__ + "." + type(self.model).__qualname__,
                "optimizer_class": type(self.optimizer).__module__ + "." + type(self.optimizer).__qualname__,
                "device": str(device), "tokenizer": contract, "tokenizer_binding": binding, "model_config": model_config,
                "parameter_schema": [{"name": name, "shape": list(value.shape), "dtype": str(value.dtype),
                                      "requires_grad": value.requires_grad}
                                     for name, value in self.model.named_parameters()],
                "state_dict_metadata": self._model_state()["state_metadata"],
                "buffer_schema": [{"name": name, "shape": list(value.shape), "dtype": str(value.dtype),
                                   "device": str(value.device)} for name, value in self.model.named_buffers()],
                "optimizer_groups": groups, "torch_version": str(self._torch().__version__)}
        if self.cache_source_epoch_marker is not None:
            configuration["cache_source_epoch_marker"] = _thaw(self.cache_source_epoch_marker)
        rotary = dict(self.model.named_modules()).get("model.rotary_emb")
        if (rotary is not None and "original_inv_freq" not in rotary._buffers and
                ((type(self.model).__module__, type(self.model).__qualname__) ==
                    ("transformers.models.llama.modeling_llama", "LlamaForCausalLM") or
                 self.model_profile is not None and (type(self.model).__module__, type(self.model).__qualname__) ==
                    ("transformers.models.qwen2.modeling_qwen2", "Qwen2ForCausalLM"))):
            value = rotary.original_inv_freq
            configuration["deterministic_plain_tensor_state"] = [{
                "name": "model.rotary_emb.original_inv_freq", "shape": list(value.shape),
                "dtype": str(value.dtype), "device": str(value.device),
                "recipe": "validated-built-in-default-rotary/v1"}]
        if self.model_profile is not None:
            configuration.update(schema="torch-complete-reviewed-decoder-configuration/v3",
                model_profile=self.model_profile, checkpoint_state_byte_limit=self._checkpoint_byte_limit(),
                padded_output_policy="reject-native-argmax-outside-tokenizer-domain/v1")
        if training_profile is not None:
            configuration.update(schema="torch-complete-reviewed-decoder-configuration/v4",
                training_conditioning_profile=training_profile)
        self._assert_pipeline(contract)
        return configuration

    def identity(self):
        signature = _digest(_json_bytes(self._configuration()))
        return {"backend_id": ("torch-digest-omitted-reviewed-decoder/v1:" if self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC else "torch-complete-reviewed-decoder/v2:") + signature,
                "implementation_sha256": _digest(Path(__file__).read_bytes()),
                "checkpoint_format": ("torch-weights-only-digest-omitted-reviewed-state-pair/v1" if self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC else "torch-weights-only-complete-reviewed-state-pair/v2"),
                "target_codec": self.target_codec, "source_conditioned": True,
                "pretrained": self.pretrained}

    def _model_state(self):
        # PyTorch passes each module's state_dict metadata to its versioned
        # load hooks. Converting only tensor entries to dict loses that data.
        state = self.model.state_dict()
        metadata = getattr(state, "_metadata", {})
        from collections import OrderedDict
        nodes = 0
        def require_json(value, depth=0):
            nonlocal nodes
            nodes += 1
            if depth > 64 or nodes > 65536:
                raise TrainingJobValidationError("bounded JSON model state-dict metadata required")
            if type(value) in (dict, OrderedDict):
                if any(type(key) is not str for key in value):
                    raise TrainingJobValidationError("JSON model state-dict metadata requires string keys")
                for child in value.values():
                    require_json(child, depth + 1)
            elif type(value) is list:
                for child in value:
                    require_json(child, depth + 1)
            elif value is None or type(value) in (str, int, bool):
                pass
            elif type(value) is float and math.isfinite(value):
                pass
            else:
                raise TrainingJobValidationError("lossless JSON model state-dict metadata values required")
        # Do not silently coerce Python tuples to lists or non-string keys to
        # strings: custom versioned load hooks may distinguish those types.
        require_json(metadata)
        try:
            metadata_raw = _json_bytes(metadata)
            metadata_copy = _parse_json(metadata_raw)
        except (TypeError, ValueError) as error:
            raise TrainingJobValidationError("JSON model state-dict metadata required") from error
        if type(metadata_copy) is not dict or len(metadata_raw) > 1024**2:
            raise TrainingJobValidationError("bounded model state-dict metadata required")
        return {"state": dict(state), "state_metadata": metadata_copy}

    def _finite_state(self, value):
        torch = self._torch()
        total = 0
        def visit(item, depth=0):
            nonlocal total
            if depth > 64:
                raise TrainingJobValidationError("Torch checkpoint nesting bound exceeded")
            if torch.is_tensor(item):
                total += item.numel() * item.element_size()
                if total > self._checkpoint_byte_limit():
                    raise TrainingJobValidationError("nonfinite or oversized Torch checkpoint tensors")
                # Bound elementwise temporaries for dense checkpoint tensors.
                # Basic narrow views retain strides (including zero strides),
                # conjugation and every logical value without a flatten copy.
                # Other layouts keep their existing native validation behavior.
                pending = [item]
                while pending:
                    chunk = pending.pop()
                    if chunk.layout != torch.strided or chunk.numel() <= 65536:
                        if not bool(torch.isfinite(chunk).all()):
                            raise TrainingJobValidationError("nonfinite or oversized Torch checkpoint tensors")
                    else:
                        axis = max(range(chunk.ndim), key=lambda dimension: chunk.shape[dimension])
                        cut = chunk.shape[axis] // 2
                        pending.append(chunk.narrow(axis, cut, chunk.shape[axis] - cut))
                        pending.append(chunk.narrow(axis, 0, cut))
            elif type(item) is dict:
                if any(type(key) not in (str, int) for key in item):
                    raise TrainingJobValidationError("unsupported Torch checkpoint dictionary key")
                for child in item.values():
                    visit(child, depth + 1)
            elif type(item) in (list, tuple):
                for child in item:
                    visit(child, depth + 1)
            elif item is not None and type(item) not in (str, int, float, bool):
                raise TrainingJobValidationError("unsupported Torch checkpoint value")
            elif type(item) is float and not math.isfinite(item):
                raise TrainingJobValidationError("nonfinite Torch checkpoint scalar")
        visit(value)

    def _chatml_frame(self, wire, conditioning_profile, contract):
        from ...logic.autoformal.training_cycle_inputs import MAX_REVIEWED_ARTIFACT_BYTES
        if type(conditioning_profile) is not str or conditioning_profile not in ({"chatml-complete-legal-ir/v1", REVIEWED_DIGEST_OMITTED_CHATML_PROFILE} | _REVIEWED_QWEN2_CHATML_PROFILES):
            raise TrainingJobValidationError("explicit supported ChatML conditioning profile required")
        if (conditioning_profile == REVIEWED_DIGEST_OMITTED_CHATML_PROFILE) != (self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC):
            raise TrainingJobValidationError("ChatML codec/profile mismatch")
        qwen2_chatml = conditioning_profile in (_REVIEWED_QWEN2_CHATML_PROFILES | {REVIEWED_DIGEST_OMITTED_CHATML_PROFILE})
        vocab, bos, eos = (contract[key] for key in ("vocab_size", "bos_token_id", "eos_token_id"))
        if type(self.tokenizer) is not ReviewedPretrainedTokenizer or self.tokenizer.allow_fictional_fixture:
            raise TrainingJobValidationError("ChatML requires the actual maintained fast tokenizer")
        native, _ = self.tokenizer._fast_backend()
        chatml_start = bos
        if qwen2_chatml:
            chatml_start = native.token_to_id("<|im_start|>")
            if (type(chatml_start) is not int or not 0 <= chatml_start < vocab or
                    chatml_start in (bos, eos) or native.id_to_token(bos) != "<|endoftext|>" or
                    native.id_to_token(eos) != "<|im_end|>"):
                raise TrainingJobValidationError("Qwen2 ChatML requires exact distinct native BOS/start/end marker mapping")
        elif (bos != 1 or eos != 2 or native.id_to_token(bos) != "<|im_start|>" or
                native.id_to_token(eos) != "<|im_end|>"):
            raise TrainingJobValidationError("ChatML requires exact native start/end marker mapping")
        # Fixed public task/schema only: no reference target, selected
        # answer, corpus value or caller-supplied decoder prefix.
        instruction = ("Translate the supplied source and permitted context into one complete LegalIR object. "
            "Output only canonical JSON with these keys: argument_roles, assumptions, cross_references, "
            "definition_uses, governing_context, interpretation_id, profile, source_binding, typed_expression. "
            "Use complete-reviewed-norm-json/v2 and TypedExpression@1. Preserve actors, modalities, ordered "
            "arguments, typed binders, conditions, exceptions, quantities, time, definitions and scope. "
            "Use no facts outside the supplied data. If required meaning or dependencies are missing, emit no body and end.")
        if conditioning_profile in {REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE, REVIEWED_DIGEST_OMITTED_CHATML_PROFILE}:
            # Public wire layouts only; never caller schema, target values,
            # an answer prefix or permission to synthesize missing facts.
            instruction += ' Public field layouts (type notation, not answer values): argument_roles is an array of objects {"symbol":string,"roles":[string]}, never an array of strings. assumptions is an array. governing_context and source_binding have exactly the fields provided in the user source wire; interpretation_id is the supplied selection identifier. typed_expression is a complete TypedExpression@1 object: interface, schema_version, expression_id, root, signature, family, profile, content_digest, metadata, and optional range; root is a typed LogicNode with kind, symbol, arguments, binders, sort, node_id, schema_version, metadata, and optional range. definition_uses entries have definition_unit_id, defined_predicate, use_unit_id, use_occurrence_cid, target_typed_paths (nonempty string array), applicability, interpretation_id, evidence_refs. cross_references entries have from_unit_id, dependency_artifact_id, dependency_sha256, version, evidence_refs. Each evidence_refs entry has artifact_id and sha256. Copy no example answer. Do not invent dependencies, identities, symbols or missing meaning, and do not emit repeated filler. Missing required facts require an empty body and EOS. Canonical JSON uses lexicographically sorted keys and no insignificant whitespace, comments or Markdown.'
        if conditioning_profile == REVIEWED_DIGEST_OMITTED_CHATML_PROFILE:
            instruction = instruction.replace("Use complete-reviewed-norm-json/v2 and TypedExpression@1.",
                "Use complete-reviewed-norm-digest-omitted-json/v1 and TypedExpression@1.")
            instruction = instruction.replace("profile, content_digest, metadata", "profile, metadata")
            instruction += " Omit ONLY typed_expression.content_digest. Do not supply that field, even empty or null; its deterministic value is assembled after generation. Keep expression_id, every node_id, signature, binders, sorts, ordered roles, source and dependency identities/hashes unchanged from the supplied facts. No other missing field is filled."
        frame_text = ("<|im_start|>system\n" + instruction + "<|im_end|>\n"
            "<|im_start|>user\n" + wire + "<|im_end|>\n<|im_start|>assistant\n")
        if len(frame_text.encode("utf-8")) > MAX_REVIEWED_ARTIFACT_BYTES:
            raise TrainingJobValidationError("complete ChatML framing exceeds existing artifact byte bound")
        offered_frame = self.tokenizer.encode(frame_text)
        if type(offered_frame) is not list:
            raise TrainingJobValidationError("ordinary complete ChatML token list required")
        # The fixed assistant role supplies the input-side prefix.
        # Logical output BOS is a transport boundary, not an extra
        # input token: Qwen2's BOS differs from the message marker.
        # Reserve every possible answer-body token and EOS.
        frame = list(offered_frame)
        if (any(type(value) is not int or not 0 <= value < vocab for value in frame) or
                frame.count(chatml_start) != 3 or frame.count(eos) != 2 or
                qwen2_chatml and frame.count(bos) != 0 or
                self.tokenizer.decode(list(frame)) != frame_text):
            raise TrainingJobValidationError("Qwen2 ChatML complete lossless source/task/role framing required" if qwen2_chatml else
                "complete lossless ChatML source/task/role framing required")
        return frame

    def validate_training_records(self, records, *, max_source_tokens, max_target_tokens):
        torch = self._torch()
        config = self._configuration()
        vocab = config["tokenizer"]["vocab_size"]
        if type(vocab) is not int or vocab < 3:
            raise TrainingJobValidationError("invalid pretrained tokenizer vocabulary")
        for embedding in (self.model.get_input_embeddings(), self.model.get_output_embeddings()):
            if embedding is None or embedding.weight.shape[0] < vocab:
                raise TrainingJobValidationError("model embeddings do not cover declared tokenizer IDs")
        self._finite_state(self._model_state())
        if type(records) is not list or not records:
            raise TrainingJobValidationError("nonempty complete reviewed records required")
        for row in records:
            if type(row) is not dict or set(row) != {"id", "unit_id", "source_wire", "target_json", "source_token_ids", "target_token_ids"}:
                raise TrainingJobValidationError("closed complete reviewed Torch record required")
            for key, limit in (("source_token_ids", max_source_tokens), ("target_token_ids", max_target_tokens)):
                tokens = row[key]
                if (type(tokens) is not list or not 3 <= len(tokens) <= limit or
                        any(type(value) is not int or not 0 <= value < vocab for value in tokens) or
                        tokens[0] != self.tokenizer.bos_token_id or tokens[-1] != self.tokenizer.eos_token_id or
                        any(value in (self.tokenizer.bos_token_id, self.tokenizer.eos_token_id) for value in tokens[1:-1])):
                    raise TrainingJobValidationError("complete untruncated Torch input and output tokens required")
                if self.tokenizer.decode(tokens[1:-1]) != row["source_wire" if key == "source_token_ids" else "target_json"]:
                    raise TrainingJobValidationError("Torch token transport differs from full source/target")
            if self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC:
                from ...logic.autoformal.training_cycle_inputs import assemble_reviewed_decoder_digest_omitted_target
                try:
                    assemble_reviewed_decoder_digest_omitted_target(row["target_json"], target_codec=self.target_codec)
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    raise TrainingJobValidationError("strict digest-omitted training target required") from exc
            lengths = (len(row["source_token_ids"]), len(row["target_token_ids"]))
            used = sum(lengths) if self.architecture == "causal_lm" else max(lengths)
            if config.get("training_conditioning_profile") is not None:
                used = len(self._chatml_frame(row["source_wire"], config["training_conditioning_profile"], config["tokenizer"])) + lengths[1] - 1
            if used > self.max_sequence_tokens:
                raise TrainingJobValidationError("full source and target exceed actual decoder context; truncation forbidden")
        # Merely validating representability does not construct a model or fit.
        if not callable(getattr(torch, "save", None)) or not callable(getattr(torch, "load", None)):
            raise TrainingJobValidationError("Torch checkpoint support unavailable")
        if _reviewed_training_conditioning_profile(self.training_conditioning_profile, self.architecture, self.model_profile) != config.get("training_conditioning_profile"):
            raise TrainingJobValidationError("training conditioning profile changed during validation")
        self._assert_pipeline(config["tokenizer"])

    def _load_pair(self, model_bytes, optimizer_bytes):
        import io
        torch = self._torch()
        for raw in (model_bytes, optimizer_bytes):
            if type(raw) is not bytes or not 0 < len(raw) <= self._checkpoint_byte_limit():
                raise TrainingJobValidationError("bounded model and optimizer Torch checkpoint bytes required")
        try:
            model = torch.load(io.BytesIO(model_bytes), map_location="cpu", weights_only=True)
            optimizer = torch.load(io.BytesIO(optimizer_bytes), map_location="cpu", weights_only=True)
        except Exception as error:
            raise TrainingJobValidationError("weights-only Torch checkpoint load failed") from error
        try:
            config = self._configuration()
        except TrainingJobValidationError as error:
            # Live model/optimizer restoration occurs only after this stage;
            # operational callback exceptions are not converted or swallowed.
            raise TrainingJobValidationError("Torch checkpoint configuration or paired state schema differs") from error
        signature = _digest(_json_bytes(config))
        if (type(model) is not dict or set(model) != {"schema", "configuration_sha256", "state", "state_metadata"} or
                model["schema"] != "torch-reviewed-model-state/v2" or model["configuration_sha256"] != signature or
                type(model["state"]) is not dict or type(model["state_metadata"]) is not dict or
                model["state_metadata"] != self._model_state()["state_metadata"] or
                type(optimizer) is not dict or set(optimizer) != {"schema", "configuration_sha256", "state", "optimizer_steps", "cpu_rng", "device_rng"} or
                optimizer["schema"] != "torch-reviewed-optimizer-state/v1" or optimizer["configuration_sha256"] != signature or
                type(optimizer["optimizer_steps"]) is not int or not 0 <= optimizer["optimizer_steps"] <= 10**9):
            raise TrainingJobValidationError("Torch checkpoint configuration or paired state schema differs")
        self._finite_state(model)
        self._finite_state(optimizer)
        def rng_state(value):
            return (torch.is_tensor(value) and value.dtype == torch.uint8 and value.ndim == 1
                    and 0 < value.numel() <= 1024 * 1024)
        device = next(self.model.parameters()).device
        if (not rng_state(optimizer["cpu_rng"]) or
                (device.type == "cuda" and not rng_state(optimizer["device_rng"])) or
                (device.type != "cuda" and optimizer["device_rng"] is not None)):
            raise TrainingJobValidationError("complete owned Torch RNG state required before restore")
        self._assert_pipeline(config["tokenizer"])
        return model, optimizer

    def inspect_checkpoint(self, model_bytes, optimizer_bytes):
        _, optimizer = self._load_pair(model_bytes, optimizer_bytes)
        return {"optimizer_steps": optimizer["optimizer_steps"]}

    def restore_checkpoint(self, model_bytes, optimizer_bytes, *, execution_guard=None):
        if execution_guard is not None and not callable(execution_guard):
            raise TrainingJobValidationError("callable restoration execution guard required")
        if execution_guard is not None:
            execution_guard()
        torch = self._torch()
        model, optimizer = self._load_pair(model_bytes, optimizer_bytes)
        from collections import OrderedDict
        state = OrderedDict(model["state"])
        state._metadata = model["state_metadata"]
        contract = self._pipeline_contract()
        self._assert_pipeline(contract)
        self.model.load_state_dict(state, strict=True)
        self._assert_pipeline(contract)
        self.optimizer.load_state_dict(optimizer["state"])
        self._assert_pipeline(contract)
        torch.set_rng_state(optimizer["cpu_rng"])
        device = next(self.model.parameters()).device
        if device.type == "cuda":
            if optimizer["device_rng"] is None:
                raise TrainingJobValidationError("owned CUDA RNG checkpoint missing")
            torch.cuda.set_rng_state(optimizer["device_rng"], device=device)
        elif optimizer["device_rng"] is not None:
            raise TrainingJobValidationError("unexpected device RNG for CPU checkpoint")
        self._optimizer_steps = optimizer["optimizer_steps"]
        self._assert_pipeline(contract)
        # Verification decodes the original pair independently. Drop the first
        # decoded model and its state-dict view before that second load; the
        # live model/optimizer own their restored state, and all byte/RNG checks
        # below still run against the unchanged checkpoint bytes.
        del state, model, optimizer
        if execution_guard is not None:
            # The caller can recheck current policy and reclaim unused heap
            # after the first decoded objects die, before independent decoding.
            execution_guard()
        if not self.restored_checkpoint_matches(model_bytes, optimizer_bytes):
            raise TrainingJobValidationError("Torch model/optimizer state did not restore exactly")

    def _same(self, left, right):
        torch = self._torch()
        if torch.is_tensor(left) or torch.is_tensor(right):
            if not (torch.is_tensor(left) and torch.is_tensor(right) and left.dtype == right.dtype and
                    tuple(left.shape) == tuple(right.shape)):
                return False
            left = left.detach().cpu().resolve_conj().resolve_neg().contiguous()
            right = right.detach().cpu().resolve_conj().resolve_neg().contiguous()
            # Numerical equality loses the sign of finite zero in parameters
            # and Adam moments. Preserve its existing NaN behavior, then check
            # logical value bytes independently of strides and scalar shape.
            return (torch.equal(left, right) and
                    torch.equal(left.reshape(-1).view(torch.uint8), right.reshape(-1).view(torch.uint8)))
        if type(left) is dict and type(right) is dict:
            return set(left) == set(right) and all(self._same(left[key], right[key]) for key in left)
        if type(left) in (list, tuple) and type(right) is type(left):
            return len(left) == len(right) and all(self._same(a, b) for a, b in zip(left, right))
        return type(left) is type(right) and left == right

    def restored_checkpoint_matches(self, model_bytes, optimizer_bytes):
        torch = self._torch()
        model, optimizer = self._load_pair(model_bytes, optimizer_bytes)
        contract = self._pipeline_contract()
        device = next(self.model.parameters()).device
        device_rng = torch.cuda.get_rng_state(device) if device.type == "cuda" else None
        current_model = self._model_state()
        matches = (self._same(current_model["state"], model["state"]) and
                self._same(current_model["state_metadata"], model["state_metadata"]) and
                self._same(self.optimizer.state_dict(), optimizer["state"]) and
                self._optimizer_steps == optimizer["optimizer_steps"] and
                self._same(torch.get_rng_state(), optimizer["cpu_rng"]) and
                self._same(device_rng, optimizer["device_rng"]))
        self._assert_pipeline(contract)
        return matches

    def snapshot_checkpoint(self):
        import io
        torch = self._torch()
        config = self._configuration()
        contract = config["tokenizer"]
        signature = _digest(_json_bytes(config))
        device = next(self.model.parameters()).device
        model = {"schema": "torch-reviewed-model-state/v2", "configuration_sha256": signature,
                 **self._model_state()}
        optimizer = {"schema": "torch-reviewed-optimizer-state/v1", "configuration_sha256": signature,
                     "state": self.optimizer.state_dict(), "optimizer_steps": self._optimizer_steps,
                     "cpu_rng": torch.get_rng_state(),
                     "device_rng": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}
        result = {}
        for name, value in (("model_state", model), ("optimizer_state", optimizer)):
            self._finite_state(value)
            stream = io.BytesIO()
            torch.save(value, stream)
            raw = stream.getvalue()
            if not 0 < len(raw) <= self._checkpoint_byte_limit():
                raise TrainingJobValidationError("Torch checkpoint exceeds declared state byte limit")
            result[name] = raw
            self._assert_pipeline(contract)
        return result

    @contextmanager
    def _preserve_readonly_state(self, *, projected_model):
        """Reuse generation custody for read-only operations; cleanup must verify.

        Caller-owned admission remains external. Snapshots are not checkpoints
        or independent proof; cleanup failure preserves its original exception
        context and must not be reported as successful read-only execution.
        """
        import copy
        from collections import OrderedDict
        torch = self._torch()
        model_owner, optimizer_owner = self.model, self.optimizer
        llama_buffers = tuple((value, value.detach().clone()) for _, value in model_owner.named_buffers())
        rotary = dict(model_owner.named_modules()).get("model.rotary_emb") if projected_model else None
        plain_rotary = ((rotary, "original_inv_freq", rotary.original_inv_freq,
                         rotary.original_inv_freq.detach().clone()),) if (
            rotary is not None and "original_inv_freq" not in rotary._buffers) else ()
        parameters = tuple(model_owner.parameters())
        model_state, optimizer_state = self._model_state(), optimizer_owner.state_dict()
        self._finite_state(model_state)
        self._finite_state(optimizer_state)
        model_state = copy.deepcopy(model_state)
        optimizer_state = copy.deepcopy(optimizer_state)
        if (not parameters or parameters[0].device.type not in {"cpu", "cuda"}
                or not callable(getattr(self.model, "modules", None))):
            raise TrainingJobValidationError("one owned Torch module device required for generation")
        device = parameters[0].device
        cpu_rng = torch.get_rng_state().clone()
        device_rng = torch.cuda.get_rng_state(device).clone() if device.type == "cuda" else None
        modes = tuple((module, module.training) for module in self.model.modules())
        gradients = tuple((parameter, parameter.grad,
                           None if parameter.grad is None else parameter.grad.detach().clone(),
                           parameter.requires_grad) for parameter in parameters)
        optimizer_steps = self._optimizer_steps
        def owner_identity():
            return (id(self.model), id(self.optimizer), tuple(id(value) for value in model_owner.parameters()),
                    tuple((name, id(value)) for name, value in model_owner.named_buffers()),
                    tuple((name, id(getattr(module, name, None)), name in module._buffers)
                          for module, name, original, saved in plain_rotary),
                    tuple(id(module) for module in model_owner.modules()),
                    tuple(tuple(id(value) for value in group["params"])
                          for group in optimizer_owner.param_groups))
        original_owner_identity = owner_identity()
        try:
            yield device, owner_identity, original_owner_identity
        finally:
            # No optimizer update or gradient clearing is performed. Restore
            # original gradient objects and mixed per-module modes, not merely
            # the root flag; RNG restoration runs even if state loading fails.
            try:
                state = OrderedDict(model_state["state"])
                state._metadata = model_state["state_metadata"]
                model_owner.load_state_dict(state, strict=True)
                optimizer_owner.load_state_dict(optimizer_state)
                self._optimizer_steps = optimizer_steps
            finally:
                try:
                    with torch.no_grad():
                        for value, saved in llama_buffers:
                            value.copy_(saved)
                        for module, name, original, saved in plain_rotary:
                            if name in module._buffers or name in module._parameters:
                                # Undo a callback's changed registration through
                                # Module's public API, restoring the original
                                # plain binding before other independent state.
                                delattr(module, name)
                            setattr(module, name, original)
                            original.copy_(saved)
                        for parameter, original, saved, requires_grad in gradients:
                            parameter.requires_grad_(requires_grad)
                            if original is not None:
                                original.copy_(saved)
                            parameter.grad = original
                finally:
                    for module, training in modes:
                        module.training = training
                    torch.set_rng_state(cpu_rng)
                    if device_rng is not None:
                        torch.cuda.set_rng_state(device_rng, device=device)
            if owner_identity() != original_owner_identity:
                raise TrainingJobValidationError("generation owned model/optimizer identity changed; exact restoration unavailable")
            # A custom load hook may return successfully without restoring.
            # Verify numeric state directly, without reentering a tokenizer
            # pipeline that the failing callback may have invalidated. Python
            # retains any original failure as the context of this cleanup error.
            restored = (self._same(self._model_state(), model_state)
                and self._same(optimizer_owner.state_dict(), optimizer_state)
                and self._same(self._optimizer_steps, optimizer_steps)
                and all(self._same(value, saved) for value, saved in llama_buffers)
                and all(getattr(module, name, None) is original and name not in module._buffers
                        and self._same(original, saved) for module, name, original, saved in plain_rotary)
                and all(parameter.grad is original and parameter.requires_grad is requires_grad
                        and (original is None or self._same(original, saved))
                        for parameter, original, saved, requires_grad in gradients)
                and all(module.training is training for module, training in modes)
                and self._same(torch.get_rng_state(), cpu_rng)
                and (device_rng is None or self._same(torch.cuda.get_rng_state(device), device_rng)))
            if not restored or owner_identity() != original_owner_identity:
                raise TrainingJobValidationError("generation numeric state did not restore exactly")

    def _teacher_forced_forward(self, source, target, *, torch, device, prompt=None):
        """One unchanged teacher-forced model call shared by fit and training."""
        if self.architecture == "encoder_decoder":
            inputs = torch.tensor([source], dtype=torch.long, device=device)
            output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                decoder_input_ids=torch.tensor([target[:-1]], dtype=torch.long, device=device),
                labels=torch.tensor([target[1:]], dtype=torch.long, device=device))
        elif prompt is not None:
            # The open assistant role predicts the first body token.
            # Logical BOS is transport only; body and EOS are labels.
            inputs = torch.tensor([prompt + target[1:]], dtype=torch.long, device=device)
            labels = torch.tensor([[-100] * len(prompt) + target[1:]], dtype=torch.long, device=device)
            output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=labels)
        else:
            # The decoder model performs its own causal one-position shift.
            # The known target BOS is a prefix; only body and EOS are labels.
            inputs = torch.tensor([source + target], dtype=torch.long, device=device)
            labels = torch.tensor([[-100] * (len(source) + 1) + target[1:]], dtype=torch.long, device=device)
            output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=labels)
        return output

    def teacher_forced_fit_batch(self, records, *, execution_guard):
        """Read-only TRAIN-row model scalar losses at the current fixed state.

        No optimizer/gradient update is performed. Expected counts describe label
        geometry, not observed CE reduction or NLL. This method authenticates no
        training population, checkpoint eligibility or generalization claim;
        those remain the selected caller's responsibility. No Q3/heldout target
        access follows from this API. Returned results require verified cleanup.
        """
        if not callable(execution_guard):
            raise TrainingJobValidationError("caller-owned fit execution guard required")
        if type(records) is not list or not 1 <= len(records) <= 32:
            raise TrainingJobValidationError("bounded explicit TRAIN-only fit batch required")
        model = self.model
        projected_model = ((type(model).__module__, type(model).__qualname__) ==
                           ("transformers.models.llama.modeling_llama", "LlamaForCausalLM") or
                           self.model_profile == "builtin-qwen2-bfloat16/v1" and
                           (type(model).__module__, type(model).__qualname__) ==
                           ("transformers.models.qwen2.modeling_qwen2", "Qwen2ForCausalLM"))
        with self._preserve_readonly_state(projected_model=projected_model) as readonly_state:
            device, owner_identity, original_owner_identity = readonly_state
            execution_guard()
            self.validate_training_records(records, max_source_tokens=self.max_sequence_tokens,
                                           max_target_tokens=self.max_sequence_tokens)
            import copy
            configuration = copy.deepcopy(self._configuration())
            contract = configuration["tokenizer"]
            profile = _reviewed_training_conditioning_profile(
                self.training_conditioning_profile, self.architecture, self.model_profile)
            # Detach bounded ordinary input custody without checkpoint/model I/O.
            owned = _parse_json(_json_bytes(records))
            def current():
                execution_guard()
                if owner_identity() != original_owner_identity:
                    raise TrainingJobValidationError("fit owned model/optimizer identity changed")
                if self._configuration() != configuration:
                    raise TrainingJobValidationError("fit backend configuration changed")
                self._assert_pipeline(contract)
                if _reviewed_training_conditioning_profile(
                        self.training_conditioning_profile, self.architecture, self.model_profile) != profile:
                    raise TrainingJobValidationError("fit training conditioning profile changed")
            current()
            framed = None if profile is None else [
                self._chatml_frame(row["source_wire"], profile, contract) for row in owned]
            current()
            self.model.train(False)
            current()
            results = []
            torch = self._torch()
            with torch.no_grad():
                for index, row in enumerate(owned):
                    current()
                    source, target = row["source_token_ids"], row["target_token_ids"]
                    prompt = None if framed is None else framed[index]
                    output = self._teacher_forced_forward(source, target, torch=torch, device=device, prompt=prompt)
                    current()
                    loss = getattr(output, "loss", None)
                    if not torch.is_tensor(loss) or loss.ndim != 0 or not bool(torch.isfinite(loss)):
                        raise TrainingJobValidationError("fit requires finite scalar model loss")
                    counts = _expected_teacher_forced_position_counts(
                        len(source), len(target), encoder_decoder=self.architecture == "encoder_decoder",
                        prompt_length=None if prompt is None else len(prompt))
                    results.append({"id": row["id"], "unit_id": row["unit_id"],
                                    "model_scalar_loss": float(loss.detach().cpu()), **counts})
                    current()
            current()
            return results

    def train_batch(self, records):
        if type(self._optimizer_steps) is not int or not 0 <= self._optimizer_steps < 10**9:
            raise TrainingJobValidationError("Torch optimizer progress capacity exhausted before update")
        training_profile = _reviewed_training_conditioning_profile(
            self.training_conditioning_profile, self.architecture, self.model_profile)
        torch = self._torch()
        self.validate_training_records(records, max_source_tokens=self.max_sequence_tokens,
                                       max_target_tokens=self.max_sequence_tokens)
        contract = self._pipeline_contract()
        def current():
            self._assert_pipeline(contract)
            if _reviewed_training_conditioning_profile(self.training_conditioning_profile, self.architecture, self.model_profile) != training_profile:
                raise TrainingJobValidationError("training conditioning profile changed during decoder callback")
        current()
        framed = None
        if training_profile is not None:
            framed = [self._chatml_frame(row["source_wire"], training_profile, contract) for row in records]
            current()

        device = next(self.model.parameters()).device
        self.model.train()
        current()
        self.optimizer.zero_grad(set_to_none=True)
        current()
        losses = []
        expected_counts = dict.fromkeys(_EXPECTED_TEACHER_FORCED_COUNT_KEYS, 0)
        for index, row in enumerate(records):
            current()
            source, target = row["source_token_ids"], row["target_token_ids"]
            row_counts = _expected_teacher_forced_position_counts(
                len(source), len(target), encoder_decoder=self.architecture == "encoder_decoder",
                prompt_length=None if framed is None else len(framed[index]))
            for key, count in row_counts.items():
                expected_counts[key] += count
            output = self._teacher_forced_forward(
                source, target, torch=torch, device=device,
                prompt=None if framed is None else framed[index])
            current()
            loss = getattr(output, "loss", None)
            if not torch.is_tensor(loss) or loss.ndim != 0 or not bool(torch.isfinite(loss)):
                raise TrainingJobValidationError("pretrained model must return a finite scalar teacher-forced loss")
            losses.append(loss)
        loss = torch.stack(losses).mean()
        current()
        loss.backward()
        current()
        parameters = [value for value in self.model.parameters() if value.requires_grad]
        gradients = [value.grad for value in parameters if value.grad is not None]
        if not gradients or any(not bool(torch.isfinite(value).all()) for value in gradients):
            raise TrainingJobValidationError("pretrained loss produced missing or nonfinite gradients")
        norm = torch.nn.utils.clip_grad_norm_(parameters, self.gradient_clip, error_if_nonfinite=True)
        current()
        self.optimizer.step()
        self._optimizer_steps += 1
        current()
        self._finite_state(self._model_state())
        self._finite_state(self.optimizer.state_dict())
        current()
        result = {"loss": float(loss.detach().cpu()), "gradient_norm": float(norm.detach().cpu()),
                  "optimizer_steps": self._optimizer_steps,
                  "trainable_parameter_count": len(parameters), "gradient_parameter_count": len(gradients)}
        result.update(expected_counts)
        current()
        return result


    def generate_batch(self, records, *, max_output_tokens, execution_guard,
                       generation_profile="full-prefix/v1", conditioning_profile="raw-source-bos/v1",
                       max_generation_seconds=None, context_budget_profile=None, terminal_profile=None):
        """Greedy BOS-to-EOS inference on the caller-owned model.

        The original five-key source-only v2 remains unchanged. A separate
        six-key profile transports bounded explicit context DATA into the same
        encoder/input path; it does not admit that context for inference.
        This low-level numerical API grants no execution, legal-use, context,
        asset or checkpoint authority. The admitted caller supplies a guard and
        separately replays those policies. Records contain only id, unit_id,
        source_wire and source_token_ids, never a target or decoder prefix.
        The output budget includes BOS and EOS. Every input yields a disposition;
        missing EOS and malformed full-nine-field JSON are not repaired.
        The explicit CPU BF16 Llama cache profile prefills the whole source and
        BOS once, then retains every key/value position while advancing one
        generated token. Its cache is row-local and never supplied by callers.
        Full-prefix behavior remains the default; cache numerics are a separate
        profile, not a universal bit-equivalence or source-faithfulness claim.
        Opt-in ChatML conditioning supplies a fixed public LegalIR task and the
        complete source wire as system/user messages, ending with the fixed
        assistant role header. Logical output BOS identifies that role boundary;
        only autonomously generated body tokens and EOS enter answer validation.
        No generated header is stripped, target field filled or source shortened.
        The full framed prefix plus requested output passes before any forward.
        An optional positive finite time budget applies separately to each row's
        guarded autoregressive loop, after all complete-input capacity checks.
        It is checked after the current guard and before each forward, so one
        native forward plus its checks can overrun this cooperative budget.
        Observed EOS remains valid; caller/resource errors are never converted
        into time-limit outputs. None preserves the original untimed behavior.
        A separate explicit terminal profile can restrict a NEXT guarded forward
        selection to EOS after the generated body passes the existing strict
        digest-omitted codec. This is constrained selection, not an observed
        unconstrained model argmax. It never adds EOS after a budget/time exit,
        repairs a body, or judges source faithfulness. None leaves greedy calls
        and decoding traces unchanged.
        """
        if not callable(execution_guard):
            raise TrainingJobValidationError("caller-owned generation execution guard required")
        if type(max_output_tokens) is not int or not 2 <= max_output_tokens <= 65536:
            raise TrainingJobValidationError("finite generation budget including BOS and EOS required")
        self._assert_target_codec_profile()
        if terminal_profile is not None and (
                type(terminal_profile) is not str or terminal_profile != REVIEWED_DECODER_CANONICAL_TERMINAL_PROFILE
                or self.target_codec != REVIEWED_DIGEST_OMITTED_TARGET_CODEC):
            raise TrainingJobValidationError("explicit digest-omitted canonical terminal profile required")
        if (conditioning_profile == REVIEWED_DIGEST_OMITTED_CHATML_PROFILE) != (
                self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC and self.model_profile == "builtin-qwen2-bfloat16/v1"):
            raise TrainingJobValidationError("generation codec and conditioning profile differ")
        if (type(generation_profile) is not str or generation_profile not in
                {"full-prefix/v1", "builtin-llama-dynamic-kv/v1", "builtin-qwen2-dynamic-kv/v1"}):
            raise TrainingJobValidationError("closed explicit generation profile required")
        if (type(conditioning_profile) is not str or conditioning_profile not in
                ({"raw-source-bos/v1", "chatml-complete-legal-ir/v1", REVIEWED_DIGEST_OMITTED_CHATML_PROFILE} | _REVIEWED_QWEN2_CHATML_PROFILES)):
            raise TrainingJobValidationError("closed explicit conditioning profile required")
        if context_budget_profile is not None and (type(context_budget_profile) is not str or
                context_budget_profile not in {REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE,
                    REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE} or
                conditioning_profile not in (_REVIEWED_QWEN2_CHATML_PROFILES | {REVIEWED_DIGEST_OMITTED_CHATML_PROFILE})):
            raise TrainingJobValidationError("explicit matching Qwen2 context budget profile required")
        context_token_limit = (REVIEWED_QWEN2_EXPANDED_CONTEXT_MAX_TOKENS
            if context_budget_profile == REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE else
            REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if context_budget_profile is not None
            else REVIEWED_GENERATION_CONTEXT_MAX_TOKENS)
        if max_generation_seconds is not None:
            try:
                valid_duration = (type(max_generation_seconds) in (int, float)
                    and math.isfinite(max_generation_seconds))
            except OverflowError:
                valid_duration = False
            if not valid_duration or max_generation_seconds <= 0:
                raise TrainingJobValidationError("finite positive per-row generation time budget required")
        qwen2_chatml = conditioning_profile in (_REVIEWED_QWEN2_CHATML_PROFILES | {REVIEWED_DIGEST_OMITTED_CHATML_PROFILE})
        chatml = qwen2_chatml or conditioning_profile == "chatml-complete-legal-ir/v1"
        cached_llama = generation_profile in {"builtin-llama-dynamic-kv/v1", "builtin-qwen2-dynamic-kv/v1"}
        execution_guard()
        import copy
        from collections import OrderedDict
        from ...logic.autoformal.training_cycle_inputs import (
            ReviewedDecoderInputValidationError, _reviewed_wire, _reviewed_decoder_tokens, MAX_REVIEWED_ARTIFACT_BYTES)
        from .legal_ir_semantic_metrics import _complete_norm_payload_shape
        def bounded_source_records():
            if (type(records) is not list or not 1 <= len(records) <= 32
                    or type(self.max_sequence_tokens) is not int or not 3 <= self.max_sequence_tokens <= 262144):
                raise TrainingJobValidationError("bounded source-only generation batch/context required")
            identifiers, estimated_bytes = set(), 0
            for row in records:
                if type(row) is not dict or set(row) != {"id", "unit_id", "source_wire", "source_token_ids"}:
                    raise TrainingJobValidationError("closed source-only generation record required; targets forbidden")
                for key in ("id", "unit_id"):
                    if type(row[key]) is not str or not 0 < len(row[key]) <= 512:
                        raise TrainingJobValidationError("bounded generation row/unit ID required")
                if row["id"] in identifiers:
                    raise TrainingJobValidationError("unique generation row IDs required")
                identifiers.add(row["id"])
                wire, tokens = row["source_wire"], row["source_token_ids"]
                if type(wire) is not str or not 0 < len(wire) <= MAX_REVIEWED_ARTIFACT_BYTES:
                    raise TrainingJobValidationError("bounded complete generation source wire required")
                if (type(tokens) is not list or not 3 <= len(tokens) <= self.max_sequence_tokens
                        or any(type(value) is not int or not 0 <= value < 2**31 for value in tokens)):
                    raise TrainingJobValidationError("bounded plain source-only generation token IDs required")
                # Bound each field and the aggregate before copying/serializing
                # caller data. The existing wire owner still enforces the exact
                # escaped JSON byte bound after this conservative size check.
                estimated_bytes += len(wire.encode("utf-8")) + 11 * len(tokens) + 12 * 512 + 256
                if estimated_bytes > MAX_REVIEWED_ARTIFACT_BYTES:
                    raise TrainingJobValidationError("generation source batch exceeds existing artifact bound")
        bounded_source_records()
        try:
            original_raw = _reviewed_wire(records)
        except (ValueError, TypeError) as error:
            raise TrainingJobValidationError("bounded ordinary generation records required") from error
        owned = _parse_json(original_raw)

        # The named budget already requires exact Qwen2 conditioning above.
        # Check detached JSON before native imports for either lossless wire;
        # exact owned-model, expanded-context and full ChatML/output capacity
        # checks below remain mandatory before any forward.
        if context_budget_profile is not None:
            for row in owned:
                try:
                    source = _parse_json(row["source_wire"].encode("utf-8"))
                except (ValueError, UnicodeError) as error:
                    raise TrainingJobValidationError("canonical source-only generation JSON required") from error
        torch = self._torch()

        # Capture numeric state without checkpoint reserialization. Restoration
        # must remain possible even when a tokenizer callback changes its policy.
        model_owner, optimizer_owner = self.model, self.optimizer
        llama_model = (type(model_owner).__module__ == "transformers.models.llama.modeling_llama"
                       and type(model_owner).__qualname__ == "LlamaForCausalLM")
        qwen2_model = (self.model_profile == "builtin-qwen2-bfloat16/v1" and
            type(model_owner).__module__ == "transformers.models.qwen2.modeling_qwen2" and
            type(model_owner).__qualname__ == "Qwen2ForCausalLM")
        projected_model = llama_model or qwen2_model
        if cached_llama and ((not llama_model if generation_profile == "builtin-llama-dynamic-kv/v1" else not qwen2_model) or self.architecture != "causal_lm" or
                next(model_owner.parameters()).device.type != "cpu" or
                next(model_owner.parameters()).dtype != torch.bfloat16 or
                getattr(model_owner.config, "_attn_implementation", None) != "eager"):
            raise TrainingJobValidationError("cached generation profile requires exact CPU BF16 eager Llama")
        if chatml and ((not qwen2_model if qwen2_chatml else not llama_model) or self.architecture != "causal_lm" or
                next(model_owner.parameters()).device.type != "cpu" or
                next(model_owner.parameters()).dtype != torch.bfloat16 or
                getattr(model_owner.config, "_attn_implementation", None) != "eager"):
            raise TrainingJobValidationError("Qwen2 ChatML requires exact profiled CPU BF16 eager Qwen2" if qwen2_chatml else
                "ChatML conditioning requires exact CPU BF16 eager Llama")
        if llama_model:
            _reviewed_builtin_llama_rotary_buffers(model_owner)
        if qwen2_model:
            _reviewed_builtin_qwen2_rotary_buffers(model_owner)
        with self._preserve_readonly_state(projected_model=projected_model) as readonly_state:
            device, owner_identity, original_owner_identity = readonly_state
            configuration = self._configuration()
            contract = configuration["tokenizer"]
            vocab, bos, eos = (contract[key] for key in ("vocab_size", "bos_token_id", "eos_token_id"))
            query_identifiers = {row[key] for row in owned for key in ("id", "unit_id")}
            input_offset = 1 if chatml else 0
            framed_sources = {}
            if cached_llama:
                import transformers
                from transformers.cache_utils import DynamicCache
                legacy_cache = transformers.__version__ == "4.52.1"
                if not legacy_cache:
                    from transformers.cache_utils import DynamicLayer
                cache_layers = configuration["model_config"]["num_hidden_layers"]
                cache_heads = configuration["model_config"]["num_key_value_heads"]
                cache_dim = configuration["model_config"].get("head_dim")
                if cache_dim is None and qwen2_model:
                    cache_dim = configuration["model_config"]["hidden_size"] // configuration["model_config"]["num_attention_heads"]
                if (type(cache_layers) is not int or not 1 <= cache_layers <= 128 or
                        type(cache_heads) is not int or not 1 <= cache_heads <= 256 or
                        type(cache_dim) is not int or not 2 <= cache_dim <= 65536):
                    raise TrainingJobValidationError("bounded full-attention cached Llama configuration required")

                def check_cache(value, expected_tokens):
                    if legacy_cache:
                        # Exact 4.52.1 DynamicCache uses two owned tensor lists.
                        # Empty/skipped/partial layers or replaced caches fail.
                        if (type(value) is not DynamicCache or
                                type(value.key_cache) is not list or type(value.value_cache) is not list or
                                type(value._seen_tokens) is not int or value._seen_tokens != expected_tokens or
                                getattr(value, "offloading", False) is not False or hasattr(value, "layers") or
                                not 0 <= expected_tokens <= self.max_sequence_tokens or
                                len(value.key_cache) != (cache_layers if expected_tokens else 0) or
                                len(value.value_cache) != len(value.key_cache)):
                            raise TrainingJobValidationError("closed owned legacy cached Llama state required")
                        for key, val in zip(value.key_cache, value.value_cache):
                            if any(not torch.is_tensor(item) or item.device != device or
                                    item.dtype != torch.bfloat16 or
                                    tuple(item.shape) != (1, cache_heads, expected_tokens, cache_dim)
                                    for item in (key, val)):
                                raise TrainingJobValidationError("cached Llama source/prefix tensor shape differs")
                        return
                    # Never accept a caller cache, replacement producer object,
                    # offloading, sliding layer or a partial source/prefix.
                    if (type(value) is not DynamicCache or value.offloading is not False or
                            len(value.layers) != cache_layers or
                            not 0 <= expected_tokens <= self.max_sequence_tokens or
                            any(type(layer) is not DynamicLayer for layer in value.layers)):
                        raise TrainingJobValidationError("closed owned cached Llama state required")
                    for layer in value.layers:
                        if expected_tokens == 0:
                            if layer.is_initialized or layer.keys is not None or layer.values is not None:
                                raise TrainingJobValidationError("new row requires an empty cached Llama state")
                        elif (layer.is_initialized is not True or any(
                                not torch.is_tensor(item) or item.device != device or
                                item.dtype != torch.bfloat16 or
                                tuple(item.shape) != (1, cache_heads, expected_tokens, cache_dim)
                                for item in (layer.keys, layer.values))):
                            raise TrainingJobValidationError("cached Llama source/prefix tensor shape differs")

            def current():
                execution_guard()
                if llama_model:
                    _reviewed_builtin_llama_rotary_buffers(model_owner)
                if qwen2_model:
                    _reviewed_builtin_qwen2_rotary_buffers(model_owner)
                if owner_identity() != original_owner_identity:
                    raise TrainingJobValidationError("generation owned model/optimizer identity changed")
                self._assert_pipeline(contract)
                bounded_source_records()
                if _reviewed_wire(records) != original_raw:
                    raise TrainingJobValidationError("generation source records changed during callback")

            # All sources and full requested output budgets pass before the
            # first forward. No shorter prefix or early-EOS assumption admits
            # an otherwise oversized source/output pair.
            for row in owned:
                if type(row["unit_id"]) is not str or not 0 < len(row["unit_id"]) <= 512:
                    raise TrainingJobValidationError("bounded generation unit ID required")
                wire = row["source_wire"]
                try:
                    source = _parse_json(wire.encode("utf-8"))
                except (ValueError, UnicodeError) as error:
                    raise TrainingJobValidationError("canonical source-only generation JSON required") from error
                context_text, transport_source = None, source
                if type(source) is dict and source.get("profile") in {REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE, REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE, REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2, REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3}:
                    context_text = _reviewed_generation_context_wire(source, query_identifiers)
                    transport_source = {key: value for key, value in source.items() if key != "context"}
                    transport_source["profile"] = "reviewed-source-selection-context/v2"
                if (type(transport_source) is not dict or set(transport_source) != {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
                        or transport_source["profile"] != "reviewed-source-selection-context/v2"
                        or type(source["source_text"]) is not str or not source["source_text"]
                        or type(source["governing_context"]) is not dict or type(source["source_binding"]) is not dict
                        or type(source["selection_context"]) is not dict
                        or set(source["selection_context"]) != {"schema", "interpretation_id", "selection_mode"}
                        or source["selection_context"]["schema"] != "caller-known-interpretation-selection/v1"
                        or source["selection_context"]["selection_mode"] != "identifier_only"
                        or type(source["selection_context"]["interpretation_id"]) is not str
                        or not 0 < len(source["selection_context"]["interpretation_id"]) <= 512
                        or _json_bytes(source).decode("utf-8") != wire):
                    raise TrainingJobValidationError("complete canonical source-only selection-context v2 required")
                # These are the existing v2 transport fields, not a semantic
                # admission. Closed scalar context prevents hidden target/AST
                # dictionaries from entering through supposedly source-only keys.
                governing, binding = source["governing_context"], source["source_binding"]
                if (set(governing) != {"jurisdiction", "instrument_id", "governing_edition",
                                      "legal_as_of_utc", "valid_from_utc", "valid_until_utc"}
                        or set(binding) != {"source_version_cid", "occurrence_cid", "document_revision"}
                        or any(not (value is None and key == "valid_until_utc")
                               and (type(value) is not str or not 0 < len(value) <= 512
                                    or any(character in value for character in "\r\n\0"))
                               for key, value in governing.items())
                        or any(type(value) is not str or not 0 < len(value) <= 512
                               or any(character in value for character in "\r\n\0")
                               for value in binding.values())):
                    raise TrainingJobValidationError("closed scalar source-known v2 context and binding required")
                if context_text is not None:
                    try:
                        _reviewed_decoder_tokens(self.tokenizer, context_text, contract,
                            context_token_limit, "context")
                    except ReviewedDecoderInputValidationError as error:
                        raise TrainingJobValidationError(
                            "complete context exceeds fixed token sub-bound or lossless transport; truncation forbidden") from error
                    current()
                try:
                    tokens = _reviewed_decoder_tokens(self.tokenizer, wire, contract, self.max_sequence_tokens, "source")
                except ReviewedDecoderInputValidationError as error:
                    raise TrainingJobValidationError("complete generation source transport differs") from error
                if (type(row["source_token_ids"]) is not list
                        or any(type(value) is not int for value in row["source_token_ids"])
                        or row["source_token_ids"] != tokens):
                    raise TrainingJobValidationError("generation source IDs differ from complete tokenizer transport")
                used = len(tokens) + max_output_tokens if self.architecture == "causal_lm" else max(len(tokens), max_output_tokens)
                if chatml:
                    frame = self._chatml_frame(wire, conditioning_profile, contract)
                    used = len(frame) + max_output_tokens - 1
                    framed_sources[row["id"]] = frame
                if used > self.max_sequence_tokens:
                    raise TrainingJobValidationError("full generation budget exceeds actual decoder context; truncation forbidden")
                current()
            self.model.train(False)
            current()
            results = []
            with torch.no_grad():
                for row in owned:
                    source = framed_sources[row["id"]] if chatml else row["source_token_ids"]
                    generated = [bos]
                    generation_started = time.monotonic() if max_generation_seconds is not None else None
                    if cached_llama:
                        cache = DynamicCache() if legacy_cache else DynamicCache(config=model_owner.config)
                        check_cache(cache, 0)
                    reason, outcome, candidate, text = "output_limit_without_eos", "incomplete", None, None
                    for _ in range(max_output_tokens - 1):
                        current()
                        if (max_generation_seconds is not None and
                                time.monotonic() - generation_started >= max_generation_seconds):
                            reason = "generation_time_limit_without_eos"
                            break
                        if cached_llama:
                            prior_tokens = 0 if len(generated) == 1 else len(source) + len(generated) - 1 - input_offset
                            check_cache(cache, prior_tokens)
                            step_input = source + generated[input_offset:] if prior_tokens == 0 else generated[-1:]
                            input_ids = torch.tensor([step_input], dtype=torch.long, device=device)
                            arguments = {"input_ids": input_ids,
                                "attention_mask": torch.ones((1, len(source) + len(generated) - input_offset), dtype=torch.long, device=device),
                                "position_ids": torch.arange(prior_tokens, len(source) + len(generated) - input_offset,
                                    dtype=torch.long, device=device).unsqueeze(0),
                                "past_key_values": cache, "use_cache": True}
                        else:
                            input_ids = torch.tensor([source if self.architecture == "encoder_decoder" else source + generated[input_offset:]],
                                                     dtype=torch.long, device=device)
                            arguments = {"input_ids": input_ids, "attention_mask": torch.ones_like(input_ids)}
                        if self.architecture == "encoder_decoder":
                            arguments["decoder_input_ids"] = torch.tensor([generated], dtype=torch.long, device=device)
                        if projected_model:
                            # Project only the next-token position. The entire
                            # source/prefix still enters native self-attention;
                            # avoid retaining sequence-by-vocabulary logits.
                            arguments["logits_to_keep"] = 1
                        output = self.model(**arguments)
                        current()
                        if cached_llama:
                            if getattr(output, "past_key_values", None) is not cache:
                                raise TrainingJobValidationError("native cached Llama producer replaced owned cache")
                            check_cache(cache, len(source) + len(generated) - input_offset)
                        logits = getattr(output, "logits", None)
                        positions = (1 if projected_model else len(generated) if self.architecture == "encoder_decoder"
                                     else len(source) + len(generated))
                        if (not torch.is_tensor(logits) or not torch.is_floating_point(logits)
                                or logits.device != device or tuple(logits.shape) != (1, positions,
                                    configuration["model_config"]["vocab_size"] if qwen2_model else vocab)
                                or not bool(torch.isfinite(logits).all())):
                            raise TrainingJobValidationError("finite last-position Llama logits with exact vocabulary required" if llama_model else
                                "finite full-prefix generation logits with exact vocabulary required")
                        terminal_eos = False
                        if terminal_profile is not None and len(generated) > 1:
                            try:
                                terminal_text = self.tokenizer.decode(list(generated[1:]))
                            except (UnicodeError, KeyError):
                                current()
                            else:
                                current()
                                terminal_eos = _reviewed_decoder_codec_terminal_body(
                                    terminal_text, target_codec=self.target_codec, terminal_profile=terminal_profile)
                                current()
                        # The finite logits above belong to this actual forward.
                        # An explicit singleton EOS constraint is not its raw
                        # unconstrained argmax and is never a posthoc append.
                        token = eos if terminal_eos else int(logits[0, -1].argmax().item())
                        if qwen2_model and not 0 <= token < vocab:
                            raise TrainingJobValidationError("native Qwen2 argmax outside tokenizer token domain")
                        generated.append(token)
                        if token == bos:
                            reason, outcome = "unexpected_bos_in_output", "invalid"
                            break
                        if token == eos:
                            if len(generated) == 2:
                                reason, outcome = "empty_output", "abstained"
                            else:
                                try:
                                    text = self.tokenizer.decode(list(generated[1:-1]))
                                except (UnicodeError, KeyError):
                                    current()
                                    reason, outcome = "invalid_output_transport", "invalid"
                                else:
                                    current()
                                    try:
                                        if self.target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC:
                                            from ...logic.autoformal.training_cycle_inputs import assemble_reviewed_decoder_digest_omitted_target
                                            value = assemble_reviewed_decoder_digest_omitted_target(text, target_codec=self.target_codec)
                                            valid = True
                                        else:
                                            value = _parse_json(text.encode("utf-8"))
                                            valid = (_json_bytes(value).decode("utf-8") == text
                                                     and _complete_norm_payload_shape(value))
                                    except (ValueError, TypeError, UnicodeError, RecursionError):
                                        valid = False
                                    if valid:
                                        reason, outcome, candidate = None, "complete", value
                                    else:
                                        reason, outcome = "invalid_complete_norm_json", "invalid"
                            break
                    results.append({"id": row["id"], "unit_id": row["unit_id"], "outcome": outcome,
                                    "candidate": candidate, "generated_token_ids": list(generated),
                                    "generated_text": text, "reason": reason})
            current()
            return results


__all__ += ["ReviewedPretrainedTokenizer", "TorchReviewedDecoderBackend"]


def _reviewed_decoder_codec_terminal_body(model_wire, *, target_codec, terminal_profile):
    """Recognize only a complete generated body using the existing public codec.

    A valid semantic mutation remains eligible. No source/reference/gold,
    dependency resolver, repaired output or legal correctness enters here.
    Invalid/incomplete bodies simply keep the normal next-token selection.
    """
    if (type(terminal_profile) is not str or terminal_profile != REVIEWED_DECODER_CANONICAL_TERMINAL_PROFILE
            or type(target_codec) is not str or target_codec != REVIEWED_DIGEST_OMITTED_TARGET_CODEC):
        raise TrainingJobValidationError("explicit matching codec terminal profile required")
    if type(model_wire) is not str:
        return False
    from ...logic.autoformal.training_cycle_inputs import assemble_reviewed_decoder_digest_omitted_target
    try:
        assemble_reviewed_decoder_digest_omitted_target(model_wire, target_codec=target_codec)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False
    return True


def _reviewed_decoder_generation_policy(value):
    """Closed opt-in inference DATA, never execution or legal-use authority."""
    if type(value) is dict and value.get("schema") == REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA:
        fields = {"schema", "generation_profile", "conditioning_profile", "max_generation_seconds",
                  "context_budget_profile", "target_codec", "terminal_profile"}
        if (set(value) != fields or type(value["terminal_profile"]) is not str
                or value["terminal_profile"] != REVIEWED_DECODER_CANONICAL_TERMINAL_PROFILE):
            raise TrainingJobValidationError("closed explicit digest-omitted terminal generation policy required")
        previous = {key: item for key, item in value.items() if key != "terminal_profile"}
        previous["schema"] = REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA
        _reviewed_decoder_generation_policy(previous)
        return _parse_json(_json_bytes(value))
    if type(value) is dict and value.get("schema") == REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA:
        if (set(value) != {"schema", "generation_profile", "conditioning_profile", "max_generation_seconds", "context_budget_profile", "target_codec"}
                or type(value["target_codec"]) is not str or value["target_codec"] != REVIEWED_DIGEST_OMITTED_TARGET_CODEC
                or type(value["conditioning_profile"]) is not str or value["conditioning_profile"] != REVIEWED_DIGEST_OMITTED_CHATML_PROFILE):
            raise TrainingJobValidationError("closed digest-omitted generation policy required")
        legacy_validation = {key: item for key, item in value.items() if key != "target_codec"}
        legacy_validation.update(schema="reviewed-decoder-generation-policy/v2", conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
        _reviewed_decoder_generation_policy(legacy_validation)
        return _parse_json(_json_bytes(value))
    fields = {"schema", "generation_profile", "conditioning_profile", "max_generation_seconds"}
    qwen2 = type(value) is dict and value.get("schema") == "reviewed-decoder-generation-policy/v2"
    if qwen2:
        fields.add("context_budget_profile")
    if (type(value) is not dict or set(value) != fields or
            value["schema"] != ("reviewed-decoder-generation-policy/v2" if qwen2 else "reviewed-decoder-generation-policy/v1") or
            type(value["generation_profile"]) is not str or value["generation_profile"] != ("builtin-qwen2-dynamic-kv/v1" if qwen2 else "builtin-llama-dynamic-kv/v1") or
            type(value["conditioning_profile"]) is not str or value["conditioning_profile"] not in (_REVIEWED_QWEN2_CHATML_PROFILES if qwen2 else {"chatml-complete-legal-ir/v1"}) or
            qwen2 and (type(value["context_budget_profile"]) is not str or value["context_budget_profile"] not in {REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE, REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE})):
        raise TrainingJobValidationError("closed explicit generation policy required")
    seconds = value["max_generation_seconds"]
    try:
        valid = type(seconds) in (int, float) and math.isfinite(seconds)
    except OverflowError:
        valid = False
    if not valid or seconds <= 0:
        raise TrainingJobValidationError("finite positive generation policy time budget required")
    return _parse_json(_json_bytes(value))


def make_reviewed_decoder_source_producer(runtime, *, binding, rows, split_manifest,
        exposure_records, source_contexts, expected_source_contexts_sha256,
        expected_admission_inputs_sha256, backend_identity, assets, model_checkpoint,
        optimizer_checkpoint, max_source_tokens, max_output_tokens,
        allow_heldout_evaluation=False, context_profile=None,
        current_context_inputs_provider=None, expected_context_inputs_sha256=None,
        context_policy_guard=None, context_transport="plain_json_v1"):
    """Bind an explicitly admission-V2 runtime to source-only or reviewed-context inference."""
    return _make_reviewed_decoder_source_producer(runtime, binding=binding, rows=rows,
        split_manifest=split_manifest, exposure_records=exposure_records, source_contexts=source_contexts,
        expected_source_contexts_sha256=expected_source_contexts_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256,
        backend_identity=backend_identity, assets=assets, model_checkpoint=model_checkpoint,
        optimizer_checkpoint=optimizer_checkpoint, max_source_tokens=max_source_tokens,
        max_output_tokens=max_output_tokens, allow_heldout_evaluation=allow_heldout_evaluation,
        context_profile=context_profile, current_context_inputs_provider=current_context_inputs_provider,
        expected_context_inputs_sha256=expected_context_inputs_sha256,
        context_policy_guard=context_policy_guard, context_transport=context_transport, _admission_version="v2")


def make_reviewed_decoder_source_producer_v3(runtime, *, binding, rows, split_manifest,
        exposure_records, source_contexts, expected_source_contexts_sha256,
        expected_admission_inputs_sha256, backend_identity, assets, model_checkpoint,
        optimizer_checkpoint, max_source_tokens, max_output_tokens,
        allow_heldout_evaluation=False, context_profile=None,
        current_context_inputs_provider=None, expected_context_inputs_sha256=None,
        context_policy_guard=None, context_transport="plain_json_v1", generation_policy=None):
    """Bind admission V3 source or explicitly reviewed heldout TRAIN context."""
    return _make_reviewed_decoder_source_producer(runtime, binding=binding, rows=rows,
        split_manifest=split_manifest, exposure_records=exposure_records, source_contexts=source_contexts,
        expected_source_contexts_sha256=expected_source_contexts_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256,
        backend_identity=backend_identity, assets=assets, model_checkpoint=model_checkpoint,
        optimizer_checkpoint=optimizer_checkpoint, max_source_tokens=max_source_tokens,
        max_output_tokens=max_output_tokens, allow_heldout_evaluation=allow_heldout_evaluation,
        context_profile=context_profile, current_context_inputs_provider=current_context_inputs_provider,
        expected_context_inputs_sha256=expected_context_inputs_sha256,
        context_policy_guard=context_policy_guard, context_transport=context_transport, generation_policy=generation_policy, _admission_version="v3")


def _make_reviewed_decoder_source_producer(runtime, *, binding, rows, split_manifest,
        exposure_records, source_contexts, expected_source_contexts_sha256,
        expected_admission_inputs_sha256, backend_identity, assets, model_checkpoint,
        optimizer_checkpoint, max_source_tokens, max_output_tokens,
        allow_heldout_evaluation=False, context_profile=None,
        current_context_inputs_provider=None, expected_context_inputs_sha256=None,
        context_policy_guard=None, context_transport="plain_json_v1", generation_policy=None, _admission_version, _target_codec="complete-reviewed-norm-json/v2"):
    """Bind a trusted admitted runtime to the reviewed source evaluator.

    The caller supplies an already-loaded checkpoint pair and real execution,
    asset-policy and current-review guards. This function never restores, fits,
    downloads or grants resources. Reference rows remain in policy comparisons;
    only detached source arguments and explicitly permitted TRAIN context reach
    the source-input builder and backend.
    The returned callable exposes defensive observation() snapshots and a
    commitment-derived input_profile_id for the evaluator's existing cache key.
    Its matched-pair observation does not change the generic evaluator's false
    authentication, legal-truth, model-quality or proof-authority flags.
    """
    import stat
    from ...logic.autoformal import training_cycle_inputs as inputs
    from . import legal_span_consumer_binding as consumer
    from . import legal_ir_eval_splits as split_owner

    def need(condition, message):
        if not condition:
            raise TrainingJobValidationError(message)

    def wire(value):
        return inputs._reviewed_wire(value)

    def copy_json(value):
        return _parse_json(wire(value))

    need(_admission_version in {"v2", "v3"}, "closed reviewed producer admission domain required")
    need(type(_target_codec) is str and _target_codec in {"complete-reviewed-norm-json/v2", REVIEWED_DIGEST_OMITTED_TARGET_CODEC},
         "explicit supported producer codec required")
    digest_omitted = _target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC
    generation_copy = None if generation_policy is None else _reviewed_decoder_generation_policy(generation_policy)
    need((generation_copy is not None and generation_copy["schema"] in {REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA, REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA}) == digest_omitted,
         "explicit matching producer codec and generation policy required")
    qwen2_generation = generation_copy is not None and generation_copy["schema"] in {"reviewed-decoder-generation-policy/v2", REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA, REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA}
    context_token_limit = (REVIEWED_QWEN2_EXPANDED_CONTEXT_MAX_TOKENS if qwen2_generation
        and generation_copy["context_budget_profile"] == REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE
        else REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if qwen2_generation else REVIEWED_GENERATION_CONTEXT_MAX_TOKENS)
    state_byte_limit = 2*1024**3 if qwen2_generation else MAX_CHECKPOINT_BYTES
    need(generation_copy is None or _admission_version == "v3", "explicit generation policy requires admission V3")
    need(consumer._reviewed_binding_version(binding) == _admission_version,
         "prepared producer binding admission contract differs from explicit factory domain")
    aggregate_context = False
    if _admission_version == "v3":
        if context_profile is not None:
            from . import legal_structured_retrieval as structured
            aggregate_context = (type(context_profile) is str
                                 and context_profile == structured.AGGREGATE_CONTEXT_V4_PROFILE)
        source_only = (context_profile is None and current_context_inputs_provider is None
                       and expected_context_inputs_sha256 is None and context_policy_guard is None)
        explicit_rich_heldout = (allow_heldout_evaluation is True
            and (context_profile == consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE or aggregate_context)
            and callable(current_context_inputs_provider) and callable(context_policy_guard)
            and type(expected_context_inputs_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", expected_context_inputs_sha256) is not None)
        need(source_only or explicit_rich_heldout,
             "admission V3 rich TRAIN context requires its complete explicit heldout profile")
        from ...logic.autoformal import legal_reviewed_norm_admission_v3 as admission_owner
        validate_binding = consumer.validate_reviewed_source_span_consumer_binding_v3
        admission_profile = REVIEWED_MIXED_ADMISSION_PROFILE
    else:
        from ...logic.autoformal import legal_norm_content_adjudication_v1 as admission_owner
        validate_binding = consumer.validate_reviewed_source_span_consumer_binding_v2
        admission_profile = None

    need(type(runtime) is ReviewedDecoderRuntime, "explicit caller-owned reviewed runtime required")
    backend, tokenizer = runtime.backend, runtime.tokenizer
    if generation_copy is not None:
        need(type(backend) is TorchReviewedDecoderBackend and backend.architecture == "causal_lm"
             and type(backend.model).__module__ == ("transformers.models.qwen2.modeling_qwen2" if qwen2_generation else "transformers.models.llama.modeling_llama")
             and type(backend.model).__qualname__ == ("Qwen2ForCausalLM" if qwen2_generation else "LlamaForCausalLM")
             and (not qwen2_generation or backend.model_profile == "builtin-qwen2-bfloat16/v1"),
             "profiled generation requires the exact owned Torch Qwen2 backend" if qwen2_generation else
             "profiled generation requires the exact owned Torch Llama backend")
    need(getattr(backend, "tokenizer", None) is tokenizer, "producer backend and input builder must share the owned tokenizer")
    need(callable(getattr(backend, "generate_batch", None)), "reviewed backend.generate_batch required for producer route")
    need(type(allow_heldout_evaluation) is bool, "explicit boolean heldout opt-in required")
    need(type(max_source_tokens) is int and 3 <= max_source_tokens <= 65536,
         "finite complete source budget required")
    need(type(max_output_tokens) is int and 2 <= max_output_tokens <= 65536,
         "finite output budget including BOS and EOS required")
    for digest in (expected_source_contexts_sha256, expected_admission_inputs_sha256):
        need(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
             "exact source-context and admission commitments required")
    need(type(assets) is tuple and 1 <= len(assets) <= MAX_BASE_DEPENDENCIES
         and all(type(item) is CheckpointArtifact for item in assets),
         "explicit bounded immutable asset tuple required")
    need(len({item.path for item in assets}) == len(assets)
         and sum(item.bytes for item in assets) <= MAX_BASE_DEPENDENCY_BYTES,
         "unique bounded model/tokenizer/license asset population required")
    need(type(model_checkpoint) is CheckpointArtifact and type(optimizer_checkpoint) is CheckpointArtifact
         and model_checkpoint.path != optimizer_checkpoint.path,
         "distinct exact already-loaded checkpoint artifacts required")
    originals = [rows, split_manifest, exposure_records, source_contexts, backend_identity]
    if generation_copy is not None:
        originals.append(generation_policy)
    frozen_raw = wire(originals)
    row_copy, manifest_copy, exposure_copy, contexts_copy, identity_copy = _parse_json(frozen_raw)[:5]
    need(type(row_copy) is list and 1 <= len(row_copy) <= 32, "producer route supports one through32 complete ordered rows")
    need(_digest(wire(contexts_copy)) == expected_source_contexts_sha256,
         "source contexts differ from independently supplied commitment")
    need(type(identity_copy) is dict and set(identity_copy) == {
        "backend_id", "implementation_sha256", "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}
        and identity_copy["target_codec"] == _target_codec
        and identity_copy["source_conditioned"] is True and type(identity_copy["pretrained"]) is bool,
        "complete source-conditioned decoder identity required")
    operation = "heldout_evaluation" if allow_heldout_evaluation else "hparam_selection"
    context_enabled = context_profile is not None
    need(type(context_transport) is str and context_transport in {"plain_json_v1", "shared_json_v1", "shared_json_v2", "shared_json_v3"},
         "explicit supported admitted context transport required")
    shared_context = context_transport in {"shared_json_v1", "shared_json_v2", "shared_json_v3"}
    need(not qwen2_generation or context_profile is None or context_transport in {"shared_json_v2", "shared_json_v3"},
         "Qwen2 reviewed rich context requires explicit lossless shared_json_v2 or shared_json_v3 transport")
    shared_schema = (inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3 if context_transport == "shared_json_v3" else
                     inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2 if context_transport == "shared_json_v2"
                     else inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA)
    need(not shared_context or (_admission_version == "v3" and context_enabled and allow_heldout_evaluation),
         "shared context requires explicit admission V3 heldout rich TRAIN route")
    logical_context_bytes = (inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES if shared_context
                             else REVIEWED_GENERATION_CONTEXT_MAX_BYTES)
    rich_heldout = allow_heldout_evaluation and context_enabled
    if context_enabled:
        expected_profile = (structured.AGGREGATE_CONTEXT_V4_PROFILE if aggregate_context else
                            (consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE if _admission_version == "v3"
                             else consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE) if rich_heldout
                            else "reviewed-rich-TRAIN-context-hparam/v1")
        need(context_profile == expected_profile
             and callable(current_context_inputs_provider) and callable(context_policy_guard)
             and type(expected_context_inputs_sha256) is str
             and re.fullmatch(r"[0-9a-f]{64}", expected_context_inputs_sha256) is not None,
             "explicit complete rich TRAIN context profile for the evaluation operation and live policy required")
        from . import legal_structured_retrieval as structured
    else:
        need(current_context_inputs_provider is None and expected_context_inputs_sha256 is None
             and context_policy_guard is None, "context opt-in fields must be supplied together")
    source_paths = {"worker": Path(__file__), "inputs": Path(inputs.__file__),
        "consumer": Path(consumer.__file__), "admission": Path(admission_owner.__file__),
        "splits": Path(split_owner.__file__)}
    source_pins = _reviewed_decoder_source_pins(admission_profile=admission_profile)
    context_source_paths = {}
    context_source_pins = None
    context_implementation = None
    if context_enabled:
        package_root = Path(__file__).parents[2]
        context_source_paths = {name: Path(__file__).with_name(name) for name in (
            "legal_structured_retrieval.py", "legal_joint_retrieval.py",
            "legal_formula_codec.py", "legal_ir_grammar_decoder.py")}
        if rich_heldout:
            evaluator_name = "legal_ir_evaluation_artifacts.py"
            context_source_paths[evaluator_name] = Path(__file__).with_name(evaluator_name)
        context_source_paths["canonical_contracts.py"] = package_root / "logic/legal_ir/canonical_contracts.py"
        context_source_pins = {name: _digest(path.read_bytes()) for name, path in context_source_paths.items()}
        context_implementation = structured.implementation_pin()
        source_paths.update({"context:" + key: path for key, path in context_source_paths.items()})
    references = {}
    for item in (*assets, model_checkpoint, optimizer_checkpoint):
        need(item.path not in references or references[item.path] == item,
             "one physical input cannot declare conflicting artifact identities")
        references[item.path] = item
    stamp_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")

    def file_stamp(path):
        observed = Path(path).lstat()
        need(stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1,
             "producer inputs must remain unaliased ordinary files")
        return tuple(getattr(observed, key) for key in stamp_fields)

    paths = set(references) | {str(path) for path in source_paths.values()}
    stamps = {path: file_stamp(path) for path in paths}
    ancestry = {str(parent): (parent.lstat().st_dev, parent.lstat().st_ino, parent.lstat().st_mode)
                for path in paths for parent in Path(path).parents}
    need(all(stat.S_ISDIR(value[2]) for value in ancestry.values()), "ordinary immutable input ancestry required")
    guards = {"execution": 0, "asset_policy": 0, "current_admission": 0,
              "full_review_replay": 0, "full_file_authentication": 0, "matched_checkpoint_checks": 0}
    observation = {"schema": ("reviewed-decoder-source-producer-observation/v2" if admission_profile else
                              "reviewed-decoder-source-producer-observation/v1"), "calls": 0,
        "loaded_checkpoint_identity_scope": "exact supplied pair equals already-loaded backend at entry and exit only",
        "training_or_restore_performed": False, "resource_authority_granted": False,
        "pretrained_quality_verified": False, "process_sandbox": False, "last_call": None}
    policy = {"schema": ("reviewed-decoder-source-producer-policy/v2" if admission_profile else
                         "reviewed-decoder-source-producer-policy/v1"),
        "backend_identity": identity_copy, "assets": [asdict(item) for item in assets],
        "model_checkpoint": asdict(model_checkpoint), "optimizer_checkpoint": asdict(optimizer_checkpoint),
        "source_contexts_sha256": expected_source_contexts_sha256,
        "admission_inputs_sha256": expected_admission_inputs_sha256,
        "max_source_tokens": max_source_tokens, "max_output_tokens": max_output_tokens,
        "operation": operation, "training_requested": False, "restore_requested": False}
    if admission_profile is not None:
        observation["admission_profile"] = policy["admission_profile"] = admission_profile
    if generation_copy is not None:
        observation["schema"] = "reviewed-decoder-source-producer-observation/v4" if qwen2_generation else "reviewed-decoder-source-producer-observation/v3"
        policy.update(schema="reviewed-decoder-source-producer-policy/v4" if qwen2_generation else "reviewed-decoder-source-producer-policy/v3", generation_policy=generation_copy)
        if qwen2_generation:
            policy["runtime_profile"] = "builtin-qwen2-bfloat16/v1"
    if digest_omitted:
        policy.update(schema=("reviewed-decoder-digest-omitted-terminal-source-producer-policy/v1"
            if generation_copy["schema"] == REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA else
            "reviewed-decoder-digest-omitted-source-producer-policy/v1"),
            output_derivation={"schema": "reviewed-digest-omitted-output-assembly/v1", "target_codec": _target_codec,
                "only_computed_field": "typed_expression.content_digest", "other_default_filling": False})
        observation["schema"] = "reviewed-decoder-digest-omitted-source-producer-observation/v1"
    pair_bytes = None
    first_review = None

    def check_input_identities():
        need(runtime.backend is backend and runtime.tokenizer is tokenizer, "caller-owned producer runtime changed")
        need(wire(originals) == frozen_raw, "bound producer inputs changed")
        need(all(file_stamp(path) == expected for path, expected in stamps.items()),
             "producer source or asset file identity changed")
        for path, expected in ancestry.items():
            current = Path(path).lstat()
            need((current.st_dev, current.st_ino, current.st_mode) == expected,
                 "producer input ancestry changed")

    context_state = {"payload": None, "payload_sha256": None, "retrieval": None,
                     "population_sha256": None, "full_replays": 0,
                     "provider_checks": 0, "policy_checks": 0}

    def context_inputs():
        value = current_context_inputs_provider()
        context_state["provider_checks"] += 1
        fields = ({"schema", "components", "split_manifest", "query_rows", "retrieval_rows"} if aggregate_context else
                  {"binding", "training_rows", "split_manifest", "admission_inputs", "exposure_records", "query_rows", "retrieval_rows"})
        need(type(value) is dict and set(value) == fields,
             "closed fresh TRAIN context consumer inputs required")
        if aggregate_context:
            need(value["schema"] == structured.AGGREGATE_CONTEXT_V4_SCHEMA
                 and type(value["components"]) is list and 1 <= len(value["components"]) <= 32,
                 "explicit complete aggregate TRAIN component contract required")
            for component in value["components"]:
                need(type(component) is dict and set(component) == {
                    "admission_id", "binding", "training_rows", "admission_inputs", "exposure_records"}
                     and type(component["binding"]) is consumer.ReviewedSourceSpanConsumerBinding
                     and consumer._reviewed_binding_version(component["binding"]) == "v3",
                     "aggregate context retains existing complete V3 TRAIN bindings")
        else:
            need(type(value["binding"]) is consumer.ReviewedSourceSpanConsumerBinding,
                 "existing complete TRAIN consumer binding required")
        queries = [{"id": row["id"], "source_text": row["source_text"]} for row in row_copy]
        need(wire(value["query_rows"]) == wire(queries),
             "rich context query/source/order differs from producer population")
        need(wire(value["split_manifest"]) == wire(manifest_copy),
             "query and TRAIN context require the same complete split manifest")
        if aggregate_context:
            components = [{"admission_id": item["admission_id"],
                "binding_receipt_sha256": _digest(wire(item["binding"].receipt())),
                "training_rows_sha256": _digest(wire(item["training_rows"])),
                "admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(item["admission_inputs"]),
                "exposure_records_sha256": _digest(wire(item["exposure_records"]))}
                for item in value["components"]]
            commitment = {"schema": "reviewed-decoder-rich-context-inputs/v4", "profile": context_profile,
                "components": components,
                "split_manifest_sha256": _digest(wire(value["split_manifest"])),
                "query_rows_sha256": _digest(wire(value["query_rows"])),
                "retrieval_rows_sha256": _digest(wire(value["retrieval_rows"])),
                "admission_inputs_sha256": _digest(wire([
                    {"admission_id": item["admission_id"], "admission_inputs_sha256": item["admission_inputs_sha256"]}
                    for item in components]))}
        else:
            commitment = {"schema": "reviewed-decoder-rich-context-inputs/v1",
                "profile": context_profile,
                "binding_receipt_sha256": _digest(wire(value["binding"].receipt())),
                "training_rows_sha256": _digest(wire(value["training_rows"])),
                "split_manifest_sha256": _digest(wire(value["split_manifest"])),
                "admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(value["admission_inputs"]),
                "exposure_records_sha256": _digest(wire(value["exposure_records"])),
                "query_rows_sha256": _digest(wire(value["query_rows"])),
                "retrieval_rows_sha256": _digest(wire(value["retrieval_rows"]))}
        need(_digest(wire(commitment)) == expected_context_inputs_sha256,
             "fresh TRAIN context provider differs from independent commitment")
        return value, commitment

    def current_context(*, replay=False, full_files=False):
        value, commitment = context_inputs()
        if full_files:
            need({key: _digest(path.read_bytes()) for key, path in context_source_paths.items()}
                 == context_source_pins, "rich context source pins changed")
            need(structured.implementation_pin() == context_implementation,
                 "rich context implementation changed")
        if replay:
            if aggregate_context:
                payload = structured.consume_reviewed_contexts_v4(**value,
                    expected_query_rows_sha256=commitment["query_rows_sha256"],
                    expected_retrieval_rows_sha256=commitment["retrieval_rows_sha256"],
                    consumer=lambda complete: complete, max_context_bytes=logical_context_bytes,
                    heldout_evaluation=first_review["heldout_evaluation"])
                need(payload["schema"] == structured.AGGREGATE_CONTEXT_V4_SCHEMA
                     and payload["examples_are_complete"] is True,
                     "fresh complete aggregate TRAIN context review required")
            else:
                heldout_context = {"heldout_evaluation": first_review["heldout_evaluation"],
                                   "_admission_version": _admission_version} if rich_heldout else {}
                consume_context = structured._consume_reviewed_contexts if rich_heldout else structured.consume_reviewed_contexts_v2
                payload = consume_context(value["binding"], value["training_rows"],
                    split_manifest=value["split_manifest"], admission_inputs=value["admission_inputs"],
                    exposure_records=value["exposure_records"], query_rows=value["query_rows"],
                    retrieval_rows=value["retrieval_rows"],
                    expected_query_rows_sha256=commitment["query_rows_sha256"],
                    expected_retrieval_rows_sha256=commitment["retrieval_rows_sha256"],
                    consumer=lambda complete: complete,
                    max_context_bytes=logical_context_bytes, **heldout_context)
                need(payload["binding_receipt"]["status"] == "ready"
                     and payload["binding_receipt"]["operation"] == "training",
                     "fresh complete TRAIN context review required")
            # Full examples and governing definitions are retained verbatim.
            retrieval = {item["id"]: [{"id": example["id"], "content": example}
                         for example in item["examples"]] for item in payload["rows"]}
            need(list(retrieval) == [row["id"] for row in row_copy],
                 "complete ordered rich context population required")
            target_ids = {row[key] for row in row_copy for key in ("id", "unit_id")}
            target_digests = {_digest(wire(row["canonical_ir"])) for row in row_copy}
            target_digests.update(_digest(wire(row["canonical_ir"]["typed_expression"]))
                                  for row in row_copy)
            def screen(value):
                if type(value) is str:
                    need(value not in target_ids, "query target ID in rich producer context")
                elif type(value) in (dict, list):
                    need(_digest(wire(value)) not in target_digests,
                         "query target subtree in rich producer context")
                    for child in (list(value) + list(value.values()) if type(value) is dict else value):
                        screen(child)
            # The factory is also callable directly; generic evaluator
            # screening is therefore repeated here before pure tokenization.
            if rich_heldout:
                structured._screen_reviewed_heldout_context(list(retrieval.values()),
                    heldout_evaluation=first_review["heldout_evaluation"], reference_rows=row_copy)
            else:
                screen(list(retrieval.values()))
            population = [{"id": row["id"], "context": {
                "permitted": [], "retrieved": retrieval[row["id"]]}} for row in row_copy]
            payload_sha = _digest(wire(payload))
            population_sha = _digest(wire(population))
            if context_state["payload"] is None:
                context_state.update(payload=copy_json(payload), payload_sha256=payload_sha,
                    retrieval=copy_json(retrieval), population_sha256=population_sha)
            else:
                need(payload_sha == context_state["payload_sha256"]
                     and population_sha == context_state["population_sha256"],
                     "complete reviewed TRAIN context changed")
            context_state["full_replays"] += 1
        need(context_state["payload"] is not None,
             "full rich TRAIN context replay required before tokenization")
        policy_commitment = {"schema": "reviewed-decoder-rich-context-use-policy/v1",
            "context_profile": context_profile, "operation": operation,
            "query_binding_receipt_sha256": _digest(wire(first_review)),
            "context_inputs_sha256": expected_context_inputs_sha256,
            "rich_payload_sha256": context_state["payload_sha256"],
            "context_record_population_sha256": context_state["population_sha256"],
            "query_source_population_sha256": commitment["query_rows_sha256"],
            "split_manifest_sha256": commitment["split_manifest_sha256"],
            "training_admission_inputs_sha256": commitment["admission_inputs_sha256"],
            "context_source_sha256": context_source_pins,
            "max_source_tokens": max_source_tokens,
            "max_context_tokens": context_token_limit,
            "max_context_bytes": REVIEWED_GENERATION_CONTEXT_MAX_BYTES,
            "max_output_tokens": max_output_tokens,
            "training_requested": False, "heldout_requested": rich_heldout}
        if shared_context:
            policy_commitment.update(schema="reviewed-decoder-rich-context-use-policy/v2",
                context_transport=context_transport,
                max_expanded_context_bytes=logical_context_bytes,
                shared_context_schema=shared_schema)
        if qwen2_generation:
            policy_commitment.update(schema="reviewed-decoder-rich-context-use-policy/v3",
                context_budget_profile=generation_copy["context_budget_profile"])
        if rich_heldout:
            policy_commitment.update(
                heldout_dependency_group_sha256=context_state["payload"]["heldout_dependency_group_sha256"],
                training_dependency_manifest_sha256=context_state["payload"]["training_dependency_manifest_sha256"])
        need(context_policy_guard(copy_json(policy_commitment)) is None,
             "trusted context policy must return None or raise its original denial")
        context_state["policy_checks"] += 1
        # A callback may return a new revoked provider mapping, rather than
        # mutate the older mapping passed to the canonical consumer.
        context_inputs()
        check_input_identities()

    def current(*, replay=False, full_files=False):
        nonlocal pair_bytes, first_review
        runtime.execution_guard()
        guards["execution"] += 1
        check_input_identities()
        runtime.asset_policy_guard(copy_json(policy))
        guards["asset_policy"] += 1
        check_input_identities()
        current_admission = runtime.current_admission_provider()
        guards["current_admission"] += 1
        need(consumer.reviewed_admission_inputs_sha256(current_admission) == expected_admission_inputs_sha256,
             "current producer admission inputs changed")
        if full_files:
            need(_reviewed_decoder_source_pins(admission_profile=admission_profile) == source_pins, "producer source pins changed")
            need(copy_json(backend.identity()) == identity_copy, "producer backend identity changed")
            loaded = {}
            for path, item in references.items():
                raw = _reviewed_decoder_artifact(item, limit=state_byte_limit,
                    load=path in {model_checkpoint.path, optimizer_checkpoint.path})
                if raw is not None:
                    loaded[path] = raw
            candidate_pair = (loaded[model_checkpoint.path], loaded[optimizer_checkpoint.path])
            if pair_bytes is None:
                pair_bytes = candidate_pair
            else:
                need(candidate_pair == pair_bytes, "immutable producer checkpoint bytes changed")
            guards["full_file_authentication"] += 1
        receipt = None
        if replay:
            receipt = validate_binding(binding, row_copy,
                split_manifest=manifest_copy, admission_inputs=current_admission, exposure_records=exposure_copy)
            guards["full_review_replay"] += 1
            need(receipt["status"] == "ready" and receipt["operation"] == operation,
                 "fresh ready reviewed binding for the exact producer operation required")
            if allow_heldout_evaluation:
                expected_purpose = ((consumer.REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE if _admission_version == "v3"
                                     else consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE) if rich_heldout
                                    else consumer.REVIEWED_HELDOUT_PURPOSE)
                need(receipt["heldout_evaluation"]["purpose"] == expected_purpose,
                     "heldout purpose must match the exact source and context profile")
            need(identity_copy["pretrained"] or receipt.get("provenance_kind") == "fictional_fixture"
                 and receipt.get("fictional_fixture_allowed") is True,
                 "non-pretrained producer requires explicit fictional fixture permission")
            if first_review is None:
                first_review = copy_json(receipt)
            else:
                need(receipt == first_review, "reviewed producer admission changed")
        if context_enabled:
            current_context(replay=replay, full_files=full_files)
            current_admission = runtime.current_admission_provider()
            guards["current_admission"] += 1
            need(consumer.reviewed_admission_inputs_sha256(current_admission) == expected_admission_inputs_sha256,
                 "current producer admission inputs changed after context policy")
        check_input_identities()
        return receipt

    def match_pair():
        need(pair_bytes is not None, "authenticated producer checkpoint pair required")
        need(backend.restored_checkpoint_matches(*pair_bytes) is True,
             "already-loaded producer model/optimizer does not match supplied checkpoint pair")
        guards["matched_checkpoint_checks"] += 1
        current()

    # The full current review establishes that these rows carry admitted facts.
    # Compare independently supplied source values outside the pure builder;
    # never populate a missing context or selector from the reference target.
    current(replay=True, full_files=True)
    need(type(contexts_copy) is dict and set(contexts_copy) == {"profile", "selection_context", "rows"}
         and contexts_copy["profile"] == "reviewed-source-selection-context/v2"
         and type(contexts_copy["rows"]) is list and len(contexts_copy["rows"]) == len(row_copy),
         "complete independently supplied source contexts required")
    selection = contexts_copy["selection_context"]
    need(type(selection) is dict and set(selection) == {"schema", "interpretation_id", "selection_mode"}
         and selection["schema"] == "caller-known-interpretation-selection/v1"
         and selection["selection_mode"] == "identifier_only", "explicit source-known interpretation selector required")
    for row, context in zip(row_copy, contexts_copy["rows"], strict=True):
        need(type(context) is dict and set(context) == {"id", "unit_id", "governing_context", "source_binding"}
             and context["id"] == row["id"] and context["unit_id"] == row["unit_id"]
             and context["governing_context"] == row["canonical_ir"]["governing_context"]
             and context["source_binding"] == row["canonical_ir"]["source_binding"]
             and selection["interpretation_id"] == row["canonical_ir"]["interpretation_id"],
             "independent source context/order/unit/selector differs from current admitted facts")
    match_pair()
    commitment = {**copy_json(policy), "source_sha256": source_pins,
        "exposure_sha256": _digest(wire(exposure_copy)), "supplied_context_supported": "empty_permitted_and_retrieved_only"}
    if context_enabled:
        commitment.update(context_profile=context_profile,
            context_inputs_sha256=expected_context_inputs_sha256,
            context_records_sha256=context_state["population_sha256"],
            rich_payload_sha256=context_state["payload_sha256"],
            context_source_sha256=context_source_pins,
            max_context_tokens=context_token_limit,
            max_context_bytes=REVIEWED_GENERATION_CONTEXT_MAX_BYTES,
            supplied_context_supported="complete_replayed_TRAIN_rich_examples")
    if shared_context:
        commitment.update(context_transport=context_transport,
            max_expanded_context_bytes=logical_context_bytes,
            shared_context_schema=shared_schema)
    commitment_sha = _digest(wire(commitment))
    observation.update(input_commitment=commitment, input_commitment_sha256=commitment_sha,
        input_profile_id=("reviewed-decoder-digest-omitted-terminal-producer/v1:"
                          if digest_omitted and generation_copy["schema"] == REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA
                          else "reviewed-decoder-digest-omitted-producer/v1:" if digest_omitted else "reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2_generation
                          else "reviewed-decoder-profiled-producer/v1:" if generation_copy is not None
                          else "reviewed-decoder-rich-TRAIN-producer/v1:" if context_enabled
                          else "reviewed-decoder-source-producer/v2:" if admission_profile
                          else "reviewed-decoder-source-producer/v1:") + commitment_sha,
        factory_preflight={"reviewed_binding_ready": True, "already_loaded_pair_match": True,
            "independent_context_matches_admitted_facts": True})

    def producer(source_arguments):
        observation["calls"] += 1
        call = {"completed": False, "entry_pair_match": False, "exit_pair_match": False,
                "input_receipt": None, "raw_generation_outputs": None,
                "producer_outputs": None, "exception_type": None}
        observation["last_call"] = call
        try:
            current(replay=True, full_files=True)
            match_pair()
            call["entry_pair_match"] = True
            need(type(source_arguments) is tuple, "existing evaluator detached argument tuple required")
            arguments = list(source_arguments)
            arguments_raw = wire(arguments)
            need(len(arguments) == len(row_copy), "exact complete producer argument population required")
            for offered, row in zip(arguments, row_copy, strict=True):
                need(type(offered) is dict and set(offered) == {"id", "source_text", "context"}
                     and offered["id"] == row["id"] and offered["source_text"] == row["source_text"]
                     and type(offered["context"]) is dict and set(offered["context"]) == {"permitted", "retrieved"}
                     and offered["context"]["permitted"] == []
                     and offered["context"]["retrieved"] == (context_state["retrieval"][row["id"]]
                         if context_enabled else []),
                     "exact source arguments and explicitly bound supplied context required" if context_enabled
                     else "exact source arguments with empty supplied context required")
            # This pure API receives no reference row, admission object or registry.
            if context_enabled:
                prepared = inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,
                    source_contexts=copy_json(contexts_copy), expected_source_contexts_sha256=expected_source_contexts_sha256,
                    expected_context_records_sha256=context_state["population_sha256"],
                    tokenizer=tokenizer, max_source_tokens=max_source_tokens,
                    **({"context_transport": context_transport} if shared_context else {}),
                    **({"context_budget_profile": generation_copy["context_budget_profile"]} if qwen2_generation else {}))
            else:
                prepared = inputs.prepare_reviewed_decoder_generation_inputs(arguments,
                    source_contexts=copy_json(contexts_copy), expected_source_contexts_sha256=expected_source_contexts_sha256,
                    tokenizer=tokenizer, max_source_tokens=max_source_tokens)
            need(type(prepared) is dict and set(prepared) == {"records", "receipt"},
                 "explicit pure source-only input result required")
            records = prepared["records"]
            records_raw = wire(records)
            call["input_receipt"] = copy_json(prepared["receipt"])
            call["source_arguments_sha256"] = _digest(arguments_raw)
            call["source_records_sha256"] = _digest(records_raw)
            current()
            generation_options = ({key: generation_copy[key] for key in
                ("generation_profile", "conditioning_profile", "max_generation_seconds")} if generation_copy is not None else {})
            if qwen2_generation:
                generation_options["context_budget_profile"] = generation_copy["context_budget_profile"]
            if generation_copy is not None and generation_copy["schema"] == REVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA:
                generation_options["terminal_profile"] = generation_copy["terminal_profile"]
            generated = backend.generate_batch(records, max_output_tokens=max_output_tokens, execution_guard=current,
                **generation_options)
            need(wire(arguments) == arguments_raw and wire(records) == records_raw,
                 "producer source arguments or records mutated")
            generated = copy_json(generated)
            need(type(generated) is list and len(generated) == len(row_copy),
                 "complete ordered generation disposition population required")
            for generated_row, row in zip(generated, row_copy, strict=True):
                need(type(generated_row) is dict and set(generated_row) == {
                    "id", "unit_id", "outcome", "candidate", "generated_token_ids", "generated_text", "reason"}
                    and generated_row["id"] == row["id"] and generated_row["unit_id"] == row["unit_id"],
                     "generation identities/order or disposition fields differ")
            call["raw_generation_outputs"] = generated
            if digest_omitted:
                call["output_derivation"] = [{"id": item["id"],
                    "raw_model_text_sha256": (None if item["generated_text"] is None else _digest(item["generated_text"].encode("utf-8"))),
                    "assembled_full_target_sha256": _digest(wire(item["candidate"])) if item["outcome"] == "complete" else None,
                    "outcome": item["outcome"], "computed_field": "typed_expression.content_digest",
                    "other_fields_repaired": False} for item in generated]
            outputs = [{key: item[key] for key in ("id", "outcome", "candidate")} for item in generated]
            call["producer_outputs"] = copy_json(outputs)
        except BaseException as error:
            call["exception_type"] = type(error).__name__
            raise
        finally:
            # No restore is attempted here. The numerical owner must have
            # restored its own state before returning or raising.
            try:
                current(replay=True, full_files=True)
                match_pair()
                call["exit_pair_match"] = True
            except BaseException as error:
                call["closeout_exception_type"] = type(error).__name__
                raise
        call["completed"] = True
        return copy_json(outputs)

    def observed():
        result = {**observation, "guard_calls": guards}
        if context_enabled:
            result["context"] = {"profile": context_profile,
                "inputs_sha256": expected_context_inputs_sha256,
                "rich_payload_sha256": context_state["payload_sha256"],
                "context_records_sha256": context_state["population_sha256"],
                "context_source_sha256": context_source_pins,
                "full_replays": context_state["full_replays"],
                "provider_checks": context_state["provider_checks"],
                "policy_checks": context_state["policy_checks"],
                "context_permission_source": "trusted_caller_callback_only",
                "heldout_context_supported": rich_heldout, "context_policy_certified": False}
        return copy_json(result)

    def evaluate(*, compiler_commit, checkpoint_declarations):
        from dataclasses import replace
        from .legal_ir_evaluation_artifacts import evaluate_reviewed_source_span_producer_artifact
        declarations = copy_json(checkpoint_declarations)
        need(type(declarations) is dict and set(declarations) == {"encoder", "decoder"}
             and type(declarations["decoder"]) is dict and set(declarations["decoder"]) == {"id", "sha256"}
             and declarations["decoder"]["id"] == identity_copy["backend_id"]
             and declarations["decoder"]["sha256"] == model_checkpoint.sha256,
             "decoder declaration must bind the actual matched model checkpoint/backend")
        current(replay=True, full_files=True)
        fresh = runtime.current_admission_provider()
        guards["current_admission"] += 1
        need(consumer.reviewed_admission_inputs_sha256(fresh) == expected_admission_inputs_sha256,
             "current evaluator admission inputs changed")

        def check_evaluator_context(receipt):
            need(receipt["context_payload_sha256"] == context_state["payload_sha256"],
                 "evaluator context differs from the producer's current TRAIN replay")
            current()

        heldout_context = {"reviewed_training_context": context_inputs()[0],
                           "context_policy_guard": check_evaluator_context} if rich_heldout else {}
        if aggregate_context:
            heldout_context["reviewed_training_context_profile"] = context_profile
        try:
            artifact = evaluate_reviewed_source_span_producer_artifact(binding=binding,
                rows=row_copy, split_manifest=manifest_copy, admission_inputs=fresh,
                exposure_records=exposure_copy, compiler_commit=compiler_commit,
                input_profile={"profile_id": observation["input_profile_id"],
                    "max_source_tokens": max_source_tokens,
                    "max_context_tokens": context_token_limit if context_enabled else 1,
                    "max_output_tokens": max_output_tokens}, checkpoint_declarations=declarations,
                permitted_context=[], retrieved_examples=(copy_json(context_state["retrieval"]) if context_enabled
                    else {row["id"]: [] for row in row_copy}),
                producer=producer, allow_heldout_evaluation=allow_heldout_evaluation, **heldout_context)
        finally:
            # A provider may return a NEW revoked mapping instead of mutating
            # the older object used by the generic evaluator's finally block.
            current(replay=True, full_files=True)
            match_pair()
        return replace(artifact, metadata={**artifact.to_dict()["metadata"],
            "source_generation_observation": observed(),
            "source_generation_input_commitment_sha256": commitment_sha})

    producer.observation = observed
    producer.input_profile_id = observation["input_profile_id"]
    producer.evaluate = evaluate
    return producer


__all__ += ["make_reviewed_decoder_source_producer", "make_reviewed_decoder_source_producer_v3"]


def load_local_reviewed_decoder_runtime(*, registry, current_admission_provider,
        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,
        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,
        expected_backend_identity, expected_source_sha256,
        expected_admission_inputs_sha256, max_model_bytes,
        runtime_profile="builtin-t5-gpt2-float32/v1"):
    """Load a local decoder under the unchanged explicit admission V2 domain."""
    return _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider,
        execution_guard=execution_guard, asset_policy_guard=asset_policy_guard,
        recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact,
        tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact,
        model_checkpoint=model_checkpoint, optimizer_checkpoint=optimizer_checkpoint,
        expected_backend_identity=expected_backend_identity, expected_source_sha256=expected_source_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256, max_model_bytes=max_model_bytes,
        _admission_version="v2", _runtime_profile=runtime_profile)


def load_local_reviewed_decoder_runtime_v3(*, admission_profile, registry, current_admission_provider,
        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,
        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,
        expected_backend_identity, expected_source_sha256,
        expected_admission_inputs_sha256, max_model_bytes,
        runtime_profile="builtin-t5-gpt2-float32/v1"):
    """Load a local decoder only for the explicitly selected admission V3 domain."""
    if type(admission_profile) is not str or admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:
        raise TrainingJobValidationError("explicit mixed-sort admission V3 load profile required")
    return _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider,
        execution_guard=execution_guard, asset_policy_guard=asset_policy_guard,
        recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact,
        tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact,
        model_checkpoint=model_checkpoint, optimizer_checkpoint=optimizer_checkpoint,
        expected_backend_identity=expected_backend_identity, expected_source_sha256=expected_source_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256, max_model_bytes=max_model_bytes,
        _admission_version="v3", _runtime_profile=runtime_profile)


def _load_local_reviewed_decoder_runtime(*, registry, current_admission_provider,
        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,
        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,
        expected_backend_identity, expected_source_sha256,
        expected_admission_inputs_sha256, max_model_bytes, _admission_version, _runtime_profile,
        _source_epoch_migration=None, _target_codec="complete-reviewed-norm-json/v2", _cache_epoch_migration_artifact=None):
    """Load an explicitly profiled built-in CPU decoder and paired state.

    The caller owns live execution, license/asset policy and current admission.
    Verified license bytes are not permission. This loader downloads nothing,
    imports no caller-selected code, trains nothing and grants no resources.
    Model storage is bounded on meta tensors before CPU materialization. Success
    keeps the checkpoint's RNG; failure restores the CPU RNG seen at Torch entry.
    """
    import stat
    if type(_target_codec) is not str or _target_codec not in {"complete-reviewed-norm-json/v2", REVIEWED_DIGEST_OMITTED_TARGET_CODEC}:
        raise TrainingJobValidationError("explicit local loader target codec required")
    digest_omitted = _target_codec == REVIEWED_DIGEST_OMITTED_TARGET_CODEC
    if digest_omitted and (_admission_version != "v3" or (_source_epoch_migration is not None and
            (type(_source_epoch_migration) is not dict or _source_epoch_migration.get("profile") not in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE)))):
        raise TrainingJobValidationError("digest-omitted loader requires fresh current-source admission; no old-objective migration")
    if digest_omitted and _source_epoch_migration is not None:
        _reviewed_digest_cache_epoch_loader_context(_source_epoch_migration, model_checkpoint,
            optimizer_checkpoint, expected_backend_identity, expected_source_sha256, expected_admission_inputs_sha256)
    cache_epoch_marker = None
    if _cache_epoch_migration_artifact is not None:
        if not digest_omitted or _source_epoch_migration is not None:
            raise TrainingJobValidationError("cache receipt is exclusive to marked same-digest reload")
        cache_epoch_marker = _reviewed_digest_cache_epoch_load_receipt(_cache_epoch_migration_artifact,
            expected_backend_identity, expected_source_sha256, expected_admission_inputs_sha256)
    elif digest_omitted and _source_epoch_migration is not None:
        cache_epoch_marker = _source_epoch_migration["current_configuration"]["cache_source_epoch_marker"]
    if type(_runtime_profile) is not str or _runtime_profile not in {"builtin-t5-gpt2-float32/v1", "builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1"}:
        raise TrainingJobValidationError("explicit supported local decoder runtime profile required")
    qwen2_profile = _runtime_profile == "builtin-qwen2-bfloat16/v1"
    llama_profile = _runtime_profile in {"builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1"}
    state_limit = 2*1024**3 if qwen2_profile else MAX_REVIEWED_DECODER_STATE_BYTES
    parameter_dtype = "bfloat16" if llama_profile else "float32"
    if _admission_version not in {"v2", "v3"}:
        raise TrainingJobValidationError("closed reviewed local-loader admission domain required")
    admission_profile = REVIEWED_MIXED_ADMISSION_PROFILE if _admission_version == "v3" else None
    for callback in (current_admission_provider, execution_guard, asset_policy_guard):
        if not callable(callback):
            raise TrainingJobValidationError("explicit live decoder load guards required")
    if (type(max_model_bytes) is not int or not 1 <= max_model_bytes <= state_limit
            or type(expected_admission_inputs_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_admission_inputs_sha256) is None):
        raise TrainingJobValidationError("bounded model bytes and exact admission commitment required")
    pins = dict(expected_source_sha256) if type(expected_source_sha256) is dict else {}
    if set(pins) != REVIEWED_DECODER_SOURCE_NAMES or any(type(value) is not str or
            re.fullmatch(r"[0-9a-f]{64}", value) is None for value in pins.values()):
        raise TrainingJobValidationError("exact five reviewed decoder source pins required")
    identity = _parse_json(_json_bytes(expected_backend_identity))
    if (type(identity) is not dict or set(identity) != {"backend_id", "implementation_sha256",
            "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}
            or identity["target_codec"] != _target_codec
            or identity["source_conditioned"] is not True or type(identity["pretrained"]) is not bool):
        raise TrainingJobValidationError("exact complete reviewed decoder backend identity required")
    references = (recipe_artifact, model_config_artifact, tokenizer_artifact,
                  license_artifact, model_checkpoint, optimizer_checkpoint)
    if any(type(item) is not CheckpointArtifact for item in references) or len({item.path for item in references}) != 6:
        raise TrainingJobValidationError("six distinct exact local decoder artifacts required")
    from . import legal_span_consumer_binding as consumer
    policy = {"schema": ("reviewed-local-decoder-load-policy/v2" if admission_profile else
                         "reviewed-local-decoder-load-policy/v1"), "backend_identity": identity,
        "assets": [asdict(item) for item in references], "producer_pins": pins,
        "admission_inputs_sha256": expected_admission_inputs_sha256,
        "max_model_bytes": max_model_bytes, "device": "cpu", "dtype": parameter_dtype,
        "load_requested": True, "restore_requested": True, "training_requested": False,
        "downloads_requested": False, "resource_grant_requested": False}
    if digest_omitted:
        policy.update(schema="reviewed-local-digest-omitted-decoder-load-policy/v1", target_codec=_target_codec)
    if _source_epoch_migration is not None:
        policy["source_epoch_migration_requested"] = True
        policy["source_epoch_migration_profile"] = (REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE
            if type(_source_epoch_migration) is dict and _source_epoch_migration.get("profile") == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE
            else (REVIEWED_DECODER_READONLY_EPOCH_PROFILE
            if type(_source_epoch_migration) is dict and _source_epoch_migration.get("profile") == REVIEWED_DECODER_READONLY_EPOCH_PROFILE
            else REVIEWED_DECODER_SOURCE_EPOCH_PROFILE))
    if digest_omitted and _source_epoch_migration is not None:
        policy["source_epoch_migration_profile"] = _source_epoch_migration["profile"]
    if llama_profile:
        policy["runtime_profile"] = _runtime_profile
    if admission_profile is not None:
        policy["admission_profile"] = admission_profile
    frozen = _json_bytes([expected_backend_identity, expected_source_sha256])
    stamps = {}
    guards = {"execution": 0, "asset_policy": 0, "current_admission": 0}

    def file_stamp(item):
        path = Path(item.path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TrainingJobValidationError("local decoder assets must stay ordinary single-link files")
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns,
                tuple((str(parent), parent.lstat().st_dev, parent.lstat().st_ino, parent.lstat().st_mode)
                      for parent in path.parents))

    def current_source_pins():
        return (_reviewed_decoder_source_pins() if admission_profile is None else
                _reviewed_decoder_source_pins(admission_profile=admission_profile))

    def current():
        execution_guard()
        guards["execution"] += 1
        if current_source_pins() != pins:
            raise TrainingJobValidationError("local decoder producer source changed")
        asset_policy_guard(_parse_json(_json_bytes(policy)))
        guards["asset_policy"] += 1
        admission = current_admission_provider()
        guards["current_admission"] += 1
        if consumer.reviewed_admission_inputs_sha256(admission) != expected_admission_inputs_sha256:
            raise TrainingJobValidationError("current local decoder admission inputs changed")
        if (_json_bytes([expected_backend_identity, expected_source_sha256]) != frozen
                or current_source_pins() != pins
                or any(file_stamp(item) != stamps[item.path] for item in references if item.path in stamps)):
            raise TrainingJobValidationError("local decoder source, identity or asset binding changed")

    # Both real policies run before any artifact loader or numerical import.
    current()
    if any(not callable(getattr(registry, name, None)) for name in ("read_artifact", "artifact_path")):
        raise TrainingJobValidationError("read-only existing artifact registry protocol required before local model loading")
    recipe_raw = _reviewed_decoder_artifact(recipe_artifact, limit=1024**2)
    config_raw = _reviewed_decoder_artifact(model_config_artifact, limit=1024**2)
    tokenizer_raw = _reviewed_decoder_artifact(tokenizer_artifact, limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _reviewed_decoder_artifact(license_artifact, load=False)
    model_raw = _reviewed_decoder_artifact(model_checkpoint, limit=state_limit)
    optimizer_raw = _reviewed_decoder_artifact(optimizer_checkpoint, limit=state_limit)
    stamps.update({item.path: file_stamp(item) for item in references})
    if len({stamp[:2] for stamp in stamps.values()}) != 6:
        raise TrainingJobValidationError("local decoder artifacts require six unique physical files")
    recipe, config_data = _parse_json(recipe_raw), _parse_json(config_raw)
    tokenizer_data = _parse_json(tokenizer_raw)
    json_identities = {name: {"raw_sha256": _digest(raw), "canonical_json_sha256": _digest(_json_bytes(value))}
        for name, raw, value in (("recipe", recipe_raw, recipe), ("model_config", config_raw, config_data),
                                 ("tokenizer", tokenizer_raw, tokenizer_data))}
    # Full hashes retain the authenticated JSON identities. The native
    # tokenizer is constructed from raw bytes below; this large parsed copy
    # and the small recipe/config wire buffers have no remaining consumers.
    del tokenizer_data, recipe_raw, config_raw
    recipe_fields = {"schema", "architecture", "model_type", "max_sequence_tokens", "pretrained", "gradient_clip", "optimizer", "tokenizer"}
    if digest_omitted:
        recipe_fields.add("target_codec")
    if llama_profile:
        recipe_fields.add("parameter_dtype")
    training_recipe = qwen2_profile and type(recipe) is dict and recipe.get("schema") == (REVIEWED_DIGEST_OMITTED_RECIPE_SCHEMA if digest_omitted else "reviewed-local-decoder-recipe/v3")
    if training_recipe:
        recipe_fields.add("training_conditioning_profile")
    if (type(recipe) is not dict or set(recipe) != recipe_fields
            or recipe["schema"] != (REVIEWED_DIGEST_OMITTED_RECIPE_SCHEMA if digest_omitted else "reviewed-local-decoder-recipe/v3" if training_recipe else "reviewed-local-decoder-recipe/v2" if llama_profile else "reviewed-local-decoder-recipe/v1")
            or type(recipe["architecture"]) is not str or type(recipe["model_type"]) is not str
            or (recipe["architecture"], recipe["model_type"]) not in ({("causal_lm", "qwen2" if qwen2_profile else "llama")} if llama_profile else {("encoder_decoder", "t5"), ("causal_lm", "gpt2")})
            or type(recipe["max_sequence_tokens"]) is not int or not 3 <= recipe["max_sequence_tokens"] <= 65536
            or type(recipe["pretrained"]) is not bool or recipe["pretrained"] != identity["pretrained"]
            or type(recipe["gradient_clip"]) not in (int, float) or not math.isfinite(recipe["gradient_clip"])
            or recipe["gradient_clip"] <= 0 or type(config_data) is not dict
            or config_data.get("model_type") != recipe["model_type"]
            or any(config_data.get(key) not in (None, {}, [], "", False)
                   for key in ("auto_map", "_auto_class", "trust_remote_code", "custom_pipelines", "quantization_config"))
            or any(value not in (None, "eager") for key, value in config_data.items()
                   if "attn_implementation" in key or "attention_implementation" in key or "experts_implementation" in key)
            or any(value not in (None, {}, [], "", False) for key, value in config_data.items() if "kernel" in key)) :
        raise TrainingJobValidationError("closed strict-JSON built-in local decoder recipe/configuration required")
    if digest_omitted and recipe.get("target_codec") != _target_codec:
        raise TrainingJobValidationError("local recipe target codec differs")
    if training_recipe and (type(recipe["training_conditioning_profile"]) is not str or recipe["training_conditioning_profile"] not in ({REVIEWED_DIGEST_OMITTED_CHATML_PROFILE} if digest_omitted else _REVIEWED_QWEN2_CHATML_PROFILES)):
        raise TrainingJobValidationError("closed explicit Qwen2 training conditioning profile required")
    if llama_profile and (recipe["parameter_dtype"] != "bfloat16" or
            not any(config_data.get(key) == "bfloat16" for key in ("dtype", "torch_dtype")) or
            any(config_data.get(key) not in (None, "bfloat16") for key in ("dtype", "torch_dtype"))):
        raise TrainingJobValidationError("explicit consistent Llama BF16 recipe/configuration dtype required")
    optimizer_options, tokenizer_options = recipe["optimizer"], recipe["tokenizer"]
    if (type(optimizer_options) is not dict or set(optimizer_options) != {"learning_rate", "betas", "eps", "weight_decay"}
            or type(optimizer_options["betas"]) is not list or len(optimizer_options["betas"]) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 1
                   for value in optimizer_options["betas"])
            or any(type(optimizer_options[key]) not in (int, float) or not math.isfinite(optimizer_options[key])
                   or optimizer_options[key] <= 0 for key in ("learning_rate", "eps"))
            or type(optimizer_options["weight_decay"]) not in (int, float)
            or not math.isfinite(optimizer_options["weight_decay"]) or optimizer_options["weight_decay"] < 0
            or type(tokenizer_options) is not dict or set(tokenizer_options) != {"bos_token", "eos_token",
                "unk_token", "pad_token", "model_max_length", "clean_up_tokenization_spaces"}
            or tokenizer_options["clean_up_tokenization_spaces"] is not False
            or type(tokenizer_options["model_max_length"]) is not int
            or tokenizer_options["model_max_length"] != recipe["max_sequence_tokens"]
            or any(not (qwen2_profile and key == "unk_token" and tokenizer_options[key] is None)
                   and (type(tokenizer_options[key]) is not str or not 0 < len(tokenizer_options[key]) <= 512)
                   for key in ("bos_token", "eos_token", "unk_token"))
            or tokenizer_options["bos_token"] == tokenizer_options["eos_token"]
            or tokenizer_options["pad_token"] is not None and (type(tokenizer_options["pad_token"]) is not str
                or not 0 < len(tokenizer_options["pad_token"]) <= 512)) :
        raise TrainingJobValidationError("closed finite AdamW and lossless fast-tokenizer options required")
    current()
    import torch
    entry_rng = torch.get_rng_state().clone()
    succeeded = False
    try:
        current()
        from tokenizers import Tokenizer
        from transformers import (PreTrainedTokenizerFast, T5Config, T5ForConditionalGeneration,
                                  GPT2Config, GPT2LMHeadModel)
        native = Tokenizer.from_str(tokenizer_raw.decode("utf-8"))
        # Recipe JSON member order is not a runtime option. The fixed v1
        # constructor order matches independently prepared local checkpoints;
        # full ordered tokenizer identity remains strict and is not rewritten.
        loaded_tokenizer = PreTrainedTokenizerFast(tokenizer_object=native,
            bos_token=tokenizer_options["bos_token"], eos_token=tokenizer_options["eos_token"],
            unk_token=tokenizer_options["unk_token"], pad_token=tokenizer_options["pad_token"],
            model_max_length=tokenizer_options["model_max_length"],
            clean_up_tokenization_spaces=tokenizer_options["clean_up_tokenization_spaces"])
        tokenizer = ReviewedPretrainedTokenizer(loaded_tokenizer,
            bos_token_id=loaded_tokenizer.bos_token_id, eos_token_id=loaded_tokenizer.eos_token_id,
            vocab_size=native.get_vocab_size(with_added_tokens=True))
        # The maintained frontend owns its complete actual native backend.
        # Do not retain the original constructor tokenizer or its input wire
        # alongside the model and independent decoded checkpoint tensors.
        del native, tokenizer_raw
        current()
        if qwen2_profile:
            from transformers import Qwen2Config, Qwen2ForCausalLM
            config_class, model_class = Qwen2Config, Qwen2ForCausalLM
        elif llama_profile:
            from transformers import LlamaConfig, LlamaForCausalLM
            config_class, model_class = LlamaConfig, LlamaForCausalLM
        else:
            config_class, model_class = ((T5Config, T5ForConditionalGeneration) if recipe["model_type"] == "t5"
                                         else (GPT2Config, GPT2LMHeadModel))
        config = config_class.from_dict(config_data)
        if (type(config) is not config_class or config.model_type != recipe["model_type"]
                or config.is_encoder_decoder != (recipe["architecture"] == "encoder_decoder")):
            raise TrainingJobValidationError("built-in model configuration architecture differs")
        # Fixed eager attention cannot resolve Hub kernel implementations.
        # Refuse other declarations above rather than silently changing them.
        config._attn_implementation = "eager"
        # Select experts only through a real built-in configuration API.
        # Older non-MoE T5/GPT2 configs lack this property: inventing an
        # ordinary attribute changes their complete serialized identity.
        if isinstance(getattr(config_class, "_experts_implementation", None), property):
            config._experts_implementation = "eager"
        def dimension(name, maximum=65536):
            value = getattr(config, name, None)
            if type(value) is not int or not 1 <= value <= maximum:
                raise TrainingJobValidationError("bounded built-in model dimensions required before meta construction: " + name)
            return value
        vocab = dimension("vocab_size", 1024**2)
        if (not tokenizer.vocab_size <= vocab <= tokenizer.vocab_size+4096 if qwen2_profile else vocab != tokenizer.vocab_size):
            raise TrainingJobValidationError("model vocabulary must equal complete tokenizer vocabulary")
        if recipe["model_type"] == "t5":
            width, ff = dimension("d_model"), dimension("d_ff")
            heads, kv = dimension("num_heads", 256), dimension("d_kv")
            encoder_layers, decoder_layers = dimension("num_layers", 128), dimension("num_decoder_layers", 128)
            buckets = dimension("relative_attention_num_buckets")
            # Includes untied/materialization aliases conservatively; no storage
            # is allocated while evaluating these integer-only estimates.
            estimate = 4 * (4 * vocab * width + encoder_layers * (4 * width * heads * kv + 3 * width * ff + 3 * width)
                + decoder_layers * (8 * width * heads * kv + 3 * width * ff + 4 * width)
                + 2 * buckets * heads + 2 * width)
        elif llama_profile:
            width, ff = dimension("hidden_size"), dimension("intermediate_size")
            heads, kv_heads = dimension("num_attention_heads", 256), dimension("num_key_value_heads", 256)
            layers = dimension("num_hidden_layers", 128)
            head_dim = width//heads if qwen2_profile else dimension("head_dim")
            positions = dimension("max_position_embeddings")
            rope, _ = _reviewed_builtin_default_rotary_parameters(config, _family="qwen2" if qwen2_profile else "llama")
            if (width % heads or heads % kv_heads or head_dim != width // heads or head_dim % 2 or
                    (False if qwen2_profile else config.attention_bias is not False or config.mlp_bias is not False) or
                    type(config.tie_word_embeddings) is not bool or recipe["max_sequence_tokens"] > positions or
                    type(rope) is not dict or set(rope) != {"rope_type", "rope_theta"} or rope["rope_type"] != "default" or
                    type(rope["rope_theta"]) not in (int, float) or not math.isfinite(rope["rope_theta"]) or rope["rope_theta"] <= 0):
                raise TrainingJobValidationError("bounded default Llama attention/rotary recipe required before meta construction")
            estimate = 2 * (2 * vocab * width + layers * (2 * width * heads * head_dim + 2 * width * kv_heads * head_dim
                + 3 * width * ff + 2 * width + ((heads+2*kv_heads)*head_dim if qwen2_profile else 0)) + width) + 4 * head_dim
        else:
            width, positions = dimension("n_embd"), dimension("n_positions")
            layers, heads = dimension("n_layer", 128), dimension("n_head", 256)
            inner = 4 * width if config.n_inner is None else dimension("n_inner")
            if width % heads or config.add_cross_attention is not False:
                raise TrainingJobValidationError("fixed GPT2 self-attention dimensions/profile required")
            estimate = 4 * (2 * vocab * width + positions * width
                + layers * (4 * width * width + 2 * width * inner + 9 * width + inner) + 2 * width)
            estimate += layers * positions * positions  # Conservative causal-mask buffer profile.
        if estimate > max_model_bytes:
            raise TrainingJobValidationError("built-in model preflight tensor estimate exceeds admitted bound")
        current()
        with torch.device("meta"):
            model = model_class(config)
            if llama_profile:
                model.bfloat16()
                for name in ("inv_freq", "original_inv_freq"):
                    value = getattr(model.model.rotary_emb, name, None)
                    if not torch.is_tensor(value):
                        raise TrainingJobValidationError("known Llama rotary buffers required on meta")
                    setattr(model.model.rotary_emb, name, value.float())
            else:
                model.float()
        rotary_buffers = _reviewed_builtin_qwen2_rotary_buffers if qwen2_profile else _reviewed_builtin_llama_rotary_buffers
        causal_buffer_names = (rotary_buffers(model) if llama_profile else
            _reviewed_builtin_gpt2_causal_buffers(model) if recipe["model_type"] == "gpt2" else [])
        state_names = set(model.state_dict())
        if (any(name not in state_names and name not in causal_buffer_names for name, _ in model.named_buffers())
                or recipe["model_type"] not in {"gpt2", "llama", "qwen2"} and any(module._non_persistent_buffers_set for module in model.modules())):
            raise TrainingJobValidationError("local decoder nonpersistent buffers cannot be restored from paired checkpoint")
        plain_rotary_tensors = (() if not llama_profile or "original_inv_freq" in model.model.rotary_emb._buffers
            else (model.model.rotary_emb.original_inv_freq,))
        tensors = {id(value): value for value in (*model.parameters(), *model.buffers(), *plain_rotary_tensors)}
        model_bytes = sum(value.numel() * value.element_size() for value in tensors.values())
        if not 0 < model_bytes <= max_model_bytes or any(value.device.type != "meta" for value in tensors.values()):
            raise TrainingJobValidationError("meta model tensor bytes exceed admitted local model bound")
        current()
        model.to_empty(device="cpu")
        model.tie_weights()
        if recipe["model_type"] == "gpt2" and _reviewed_builtin_gpt2_causal_buffers(model, initialize=True) != causal_buffer_names:
            raise TrainingJobValidationError("materialized GPT2 causal buffer population differs from meta construction")
        if llama_profile and rotary_buffers(model, initialize=True) != causal_buffer_names:
            raise TrainingJobValidationError("materialized Llama rotary buffer population differs from meta construction")
        plain_rotary_tensors = (() if not llama_profile or "original_inv_freq" in model.model.rotary_emb._buffers
            else (model.model.rotary_emb.original_inv_freq,))
        cpu_tensors = {id(value): value for value in (*model.parameters(), *model.buffers(), *plain_rotary_tensors)}
        cpu_model_bytes = sum(value.numel() * value.element_size() for value in cpu_tensors.values())
        if not 0 < cpu_model_bytes <= max_model_bytes:
            raise TrainingJobValidationError("materialized tied model tensor bytes exceed admitted local model bound")
        if llama_profile:
            if (any(value.device.type != "cpu" or value.dtype != torch.bfloat16 for value in model.parameters()) or
                    any(value.device.type != "cpu" or value.dtype != torch.float32 for value in model.buffers())):
                raise TrainingJobValidationError("CPU BF16 parameters and float32 rotary buffers required after materialization")
        elif any(value.device.type != "cpu" or value.is_floating_point() and value.dtype != torch.float32
                 for value in (*model.parameters(), *model.buffers())):
            raise TrainingJobValidationError("one CPU float32 model required after materialization")
        current()
        optimizer = torch.optim.AdamW(model.parameters(), lr=optimizer_options["learning_rate"],
            betas=tuple(optimizer_options["betas"]), eps=optimizer_options["eps"],
            weight_decay=optimizer_options["weight_decay"], amsgrad=False, maximize=False,
            foreach=False, capturable=False, differentiable=False, fused=False)
        backend = TorchReviewedDecoderBackend(model, optimizer, tokenizer,
            architecture=recipe["architecture"], max_sequence_tokens=recipe["max_sequence_tokens"],
            pretrained=recipe["pretrained"], gradient_clip=recipe["gradient_clip"],
            **({"model_profile": _runtime_profile} if qwen2_profile else {}),
            **({"training_conditioning_profile": recipe["training_conditioning_profile"]} if training_recipe else {}),
            **({"target_codec": _target_codec} if digest_omitted else {}),
            **({"cache_source_epoch_marker": cache_epoch_marker} if cache_epoch_marker is not None else {}))
        if backend.identity() != identity:
            raise TrainingJobValidationError("local constructed decoder backend identity differs")
        current()
        if digest_omitted and _source_epoch_migration is not None:
            model_raw, optimizer_raw = _reviewed_digest_cache_epoch_restore(backend, model_raw, optimizer_raw,
                _source_epoch_migration, registry, current_admission_provider, current)
        elif _source_epoch_migration is not None:
            model_raw, optimizer_raw = _reviewed_epoch_restore(backend, model_raw, optimizer_raw,
                _source_epoch_migration, registry, current_admission_provider, current)
        backend.restore_checkpoint(model_raw, optimizer_raw, execution_guard=current)
        current()
        if not backend.restored_checkpoint_matches(model_raw, optimizer_raw):
            raise TrainingJobValidationError("local decoder checkpoint pair did not restore exactly")
        current()
        for item in references:
            _reviewed_decoder_artifact(item, limit=state_limit, load=False)
        runtime = ReviewedDecoderRuntime(registry, backend, tokenizer,
            current_admission_provider, execution_guard, asset_policy_guard)
        receipt = {"schema": ("reviewed-local-decoder-runtime-load/v2" if admission_profile else
                              "reviewed-local-decoder-runtime-load/v1"), "artifacts": [asdict(item) for item in references],
            "producer_pins": pins, "json_artifact_identities": json_identities,
            "expected_backend_identity": identity, "loaded_backend_identity": backend.identity(),
            "model_unique_tensor_bytes": model_bytes, "materialized_model_unique_tensor_bytes": cpu_model_bytes,
            "model_preflight_estimated_bytes": estimate,
            "attention_implementation": "eager", "max_model_bytes": max_model_bytes,
            "device": "cpu", "dtype": parameter_dtype, "guard_calls": dict(guards),
            "checkpoint_restored": True, "matched_pair": True, "optimizer_steps": backend._optimizer_steps,
            "load_performed": True, "restore_performed": True, "training_performed": False,
            "downloads_performed": False, "resource_granted": False, "license_bytes_are_permission": False,
            "pretrained_quality_verified": False, "legal_meaning_verified": False,
            "proof_authority": False, "convergence_proved": False, "corpus_admitted": False,
            "supported_profile": {"model_types": ["qwen2" if qwen2_profile else "llama"] if llama_profile else ["t5", "gpt2"], "device": "cpu", "dtype": parameter_dtype,
                "attention": "eager", "experts": "eager", "max_model_bytes": state_limit},
            "automatic_old_source_checkpoint_migration": False,
            "reconstructed_deterministic_nonpersistent_buffers": [name for name in causal_buffer_names
                if name in dict(model.named_buffers())],
            "tokenizer_constructor_option_order": ["bos_token", "eos_token", "unk_token", "pad_token",
                "model_max_length", "clean_up_tokenization_spaces"]}
        if digest_omitted:
            receipt.update(schema="reviewed-local-digest-omitted-decoder-runtime-load/v1", target_codec=_target_codec,
                old_objective_checkpoint_migration_performed=False)
        if _source_epoch_migration is not None:
            receipt["explicit_source_epoch_migration_performed"] = True
        current()
        if _cache_epoch_migration_artifact is not None:
            _reviewed_digest_cache_epoch_validate_receipt(asdict(_cache_epoch_migration_artifact), backend, expected_spec=None)
            receipt["cache_source_epoch_migration"] = asdict(_cache_epoch_migration_artifact)
            receipt["cache_source_epoch_marker"] = _thaw(backend.cache_source_epoch_marker)
            current()
        if backend.identity() != identity or not backend.restored_checkpoint_matches(model_raw, optimizer_raw):
            raise TrainingJobValidationError("loaded decoder pair changed after final policy guard")
        receipt["guard_calls"] = dict(guards)
        if llama_profile:
            plain_names = [name for name in causal_buffer_names if name not in dict(model.named_buffers())]
            if plain_names:
                receipt["reconstructed_deterministic_plain_tensor_attributes"] = plain_names
            receipt["runtime_profile"] = _runtime_profile
            receipt["deterministic_buffer_dtype"] = "float32"
        if admission_profile is not None:
            receipt["admission_profile"] = admission_profile
        succeeded = True
        return runtime, receipt
    finally:
        if not succeeded:
            torch.set_rng_state(entry_rng)


__all__ += ["load_local_reviewed_decoder_runtime", "load_local_reviewed_decoder_runtime_v3"]

# Explicit same-semantics Source transition. Default loaders and numerical
# methods retain their strict configuration equality and original behavior.
REVIEWED_DECODER_SOURCE_EPOCH_PROFILE = "3ff2e73c-to-reviewed-continuation-withdrawal-owner/v2"
REVIEWED_DECODER_SOURCE_EPOCH_CONTRACT_SCHEMA = "reviewed-decoder-source-epoch-compatibility/v1"
REVIEWED_DECODER_SOURCE_EPOCH_RECEIPT_SCHEMA = "reviewed-decoder-source-epoch-migration/v1"
REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA = "reviewed-legal-ir-decoder-checkpoint/v3"
REVIEWED_DECODER_SOURCE_EPOCH_OLD_WORKER = "3ff2e73ce45604dd86e477b865116dd34bac123ce9fa602d7766adc3fb9fe29c"
REVIEWED_DECODER_SOURCE_EPOCH_OLD_INPUTS = "9ec206c08aeef9924f7a21475b4b065376c48c5bac185c43c7911f119a319d31"
REVIEWED_DECODER_SOURCE_EPOCH_CURRENT_INPUTS = "a6883078a59ca6e3a5ae9a5fc69da5b43d1d513a3701a1d9dfe2c38b714d7049"

def _reviewed_epoch_need(condition, message):
    if not condition:
        raise TrainingJobValidationError("explicit source-epoch migration: " + message)

def _reviewed_epoch_document(reference, *, limit=MAX_CHECKPOINT_BYTES):
    raw = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(reference), limit=limit)
    value = _parse_json(raw)
    _reviewed_epoch_need(_json_bytes(value) == raw, "canonical complete metadata required")
    return value, raw

def _reviewed_epoch_code(module_code, name):
    import types
    values = [item for item in module_code.co_consts
              if isinstance(item, types.CodeType) and item.co_name == name]
    _reviewed_epoch_need(len(values) == 1, "unique maintained definition required: " + name)
    return values[0]

def _reviewed_epoch_input_source_projection(old_source, current_source):
    """Authenticate precisely the selected V4 inventory repair, not a waiver.

    Reverse its one exact byte span, recover the complete already selected
    continuation-only input body, then recover the original old source prefix.
    No tokenizer, numerical, ancestry equality or cache-mode delta is allowed.
    """
    _reviewed_epoch_need(type(old_source) is bytes and type(current_source) is bytes
        and _digest(old_source) == REVIEWED_DECODER_SOURCE_EPOCH_OLD_INPUTS
        and _digest(current_source) == REVIEWED_DECODER_SOURCE_EPOCH_CURRENT_INPUTS,
        "unsupported explicit withdrawal-owner input epoch")
    old_span = b'    modules = (sys.modules[__name__], consumer, admission, splits)\n    if multiple:\n        modules += (dependencies,)\n'
    new_span = b'    modules = (sys.modules[__name__], consumer, admission, splits)\n    # Mixed V4 retains the dependency owner during an inactive withdrawal:\n    # its producer identity belongs to the lineage, not active row presence.\n    if multiple or _admission_version == "v3":\n        modules += (dependencies,)\n'
    _reviewed_epoch_need(current_source.count(new_span) == 1,
        "exact mixed V4 producer-inventory repair is absent or duplicated")
    normalized = current_source.replace(new_span, old_span, 1)
    _reviewed_epoch_need(_digest(normalized) == "3e424c487eeea8e7123bcd51f514004b188751976e1bd3b91b5b39cc0ae3cfa8"
        and normalized.startswith(old_source),
        "unrelated input behavior or maintained old prefix changed")
    return {"rule":"exact-mixed-V4-withdrawal-producer-inventory-only/v1",
        "old_inputs_sha256":_digest(old_source),"current_inputs_sha256":_digest(current_source),
        "normalized_continuation_inputs_sha256":_digest(normalized),
        "original_prefix_bytes":len(old_source)}


def _reviewed_epoch_sources(contract, old_manifest, spec):
    """Compute the supported source difference; never execute archived source."""
    import ast
    from ...logic.autoformal import training_cycle_inputs as inputs
    required = {"schema", "profile", "old_checkpoint_manifest_sha256",
        "old_configuration_sha256", "old_tokenizer_pipeline_sha256",
        "current_configuration_sha256", "old_source_sha256", "current_source_sha256",
        "old_source_artifacts", "current_source_artifacts", "dependency_snapshot_artifact"}
    _reviewed_epoch_need(type(contract) is dict and set(contract) == required
        and contract["schema"] == REVIEWED_DECODER_SOURCE_EPOCH_CONTRACT_SCHEMA
        and contract["profile"] == REVIEWED_DECODER_SOURCE_EPOCH_PROFILE,
        "closed supported compatibility contract required")
    _reviewed_epoch_need(contract["old_checkpoint_manifest_sha256"] == spec.parent_checkpoint_artifact.sha256
        and contract["old_source_sha256"] == old_manifest["producer_pins"]
        and contract["current_source_sha256"] == _thaw(spec.expected_source_sha256)
        and set(contract["old_source_sha256"]) == REVIEWED_DECODER_SOURCE_NAMES
        and set(contract["current_source_sha256"]) == REVIEWED_DECODER_SOURCE_NAMES,
        "both exact Source5 bindings required")
    old_pins, current_pins = contract["old_source_sha256"], contract["current_source_sha256"]
    _reviewed_epoch_need(old_pins["worker"] == REVIEWED_DECODER_SOURCE_EPOCH_OLD_WORKER
        and old_pins["inputs"] == REVIEWED_DECODER_SOURCE_EPOCH_OLD_INPUTS
        and current_pins["inputs"] == REVIEWED_DECODER_SOURCE_EPOCH_CURRENT_INPUTS
        and all(old_pins[key] == current_pins[key] for key in ("consumer", "admission", "splits"))
        and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile) == current_pins,
        "unsupported source epoch or changed common producer")
    old_refs, new_refs = contract["old_source_artifacts"], contract["current_source_artifacts"]
    _reviewed_epoch_need(type(old_refs) is type(new_refs) is dict
        and set(old_refs) == set(new_refs) == {"worker", "inputs"},
        "both maintained worker/input source bodies required")
    old_bytes, new_bytes = {}, {}
    for key in ("worker", "inputs"):
        old_bytes[key] = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(old_refs[key]), limit=2*1024**2)
        new_bytes[key] = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(new_refs[key]), limit=2*1024**2)
        _reviewed_epoch_need(_digest(old_bytes[key]) == old_pins[key]
            and _digest(new_bytes[key]) == current_pins[key], "source body commitment differs")
    _reviewed_epoch_need(Path(new_refs["worker"]["path"]) == Path(__file__)
        and Path(new_refs["inputs"]["path"]) == Path(inputs.__file__),
        "current physical source origins differ")
    input_projection = _reviewed_epoch_input_source_projection(old_bytes["inputs"], new_bytes["inputs"])
    # The first profile deliberately refuses the separate parsed-cache epoch,
    # including a supposedly disabled flag: no semantic projection is assumed.
    controls = {"ReviewedMixedDecoderTrainingJobSpec", "_execute_reviewed_decoder_job",
                "_load_local_reviewed_decoder_runtime"}
    continuation = {"_reviewed_mixed_decoder_continuation_state"}
    constants = {"REVIEWED_DECODER_CONTINUATION_CHECKPOINT_SCHEMA",
        "REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE", "REVIEWED_DECODER_STAGE_CONTINUATION_SCHEMA"}
    def projection(raw, *, current):
        result, names = [], set()
        for node in ast.parse(raw).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                _reviewed_epoch_need(node.name not in names, "duplicate top-level definition")
                names.add(node.name)
                if node.name in controls:
                    continue
                if current and (node.name in continuation or node.name.startswith("_reviewed_epoch_")
                                or node.name == "migrate_local_reviewed_decoder_source_epoch_v3"):
                    continue
            if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
                keys = {target.id for target in node.targets}
                if keys == {"__all__"}:
                    _reviewed_epoch_need(isinstance(node.value, (ast.List, ast.Tuple))
                        and all(isinstance(v, ast.Constant) and type(v.value) is str for v in node.value.elts),
                        "nonliteral export mutation unsupported")
                    continue
                if current and all(key in constants or key.startswith("REVIEWED_DECODER_SOURCE_EPOCH_") for key in keys):
                    _reviewed_epoch_need(isinstance(node.value, ast.Constant) and type(node.value.value) is str,
                        "nonliteral compatibility constant unsupported")
                    continue
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
                _reviewed_epoch_need(isinstance(node.value, (ast.List, ast.Tuple))
                    and all(isinstance(v, ast.Constant) and type(v.value) is str for v in node.value.elts),
                    "nonliteral export update unsupported")
                continue
            result.append(ast.dump(node, include_attributes=False))
        return result
    _reviewed_epoch_need(projection(old_bytes["worker"], current=False)
        == projection(new_bytes["worker"], current=True),
        "numerical/tokenizer methods, globals, imports or unrelated definitions changed")
    return {"old_worker": old_bytes["worker"], "current_worker": new_bytes["worker"],
        "old_inputs": old_bytes["inputs"], "current_inputs": new_bytes["inputs"],
        "projection_sha256": _digest(_json_bytes({
            "worker_projection":projection(old_bytes["worker"], current=False),
            "input_projection":input_projection}))}

def _reviewed_epoch_pipeline(raw):
    value = _parse_json(raw)
    fields = {"schema", "kind", "backend", "frontend", "implementation", "transport"}
    _reviewed_epoch_need(type(value) is dict and set(value) == fields
        and value["schema"] == "reviewed-decoder-tokenizer-pipeline/v1"
        and value["kind"] == "huggingface_fast" and _json_bytes(value) == raw
        and type(value["implementation"]) is list
        and value["transport"] == {"body_only": True, "padding": False, "truncation": False},
        "actual complete maintained fast-tokenizer pipeline snapshot required")
    ids = value["frontend"]["wrapper_special_ids"]
    _reviewed_epoch_need(type(ids) is dict and set(ids) == {"bos_token_id", "eos_token_id", "vocab_size"}
        and all(type(item) is int for item in ids.values()), "complete tokenizer ID domain required")
    token_contract = {"schema": "reviewed-decoder-tokenizer-contract/v2", **ids,
        "pipeline_kind": "huggingface_fast", "pipeline_sha256": _digest(raw), "pipeline_bytes": len(raw)}
    model = value["backend"]["serialization"]["model"]
    vocabulary = {"model_type": model.get("type"), "vocab": model["vocab"],
                  "added_tokens": value["backend"]["serialization"]["added_tokens"]}
    binding = {"tokenizer_id": "reviewed-tokenizer:huggingface_fast:" + _digest(_json_bytes({
        "kind": value["kind"], "implementation": value["implementation"], "transport": value["transport"]})),
        "vocabulary_sha256": "sha256:" + _digest(_json_bytes(vocabulary)),
        "configuration_sha256": "sha256:" + _digest(raw), **ids}
    return value, token_contract, binding

def _reviewed_epoch_pipeline_proof(old_raw, current_raw, sources, old_pins, current_pins):
    """Only the authenticated maintained-file/code-location provenance may differ."""
    import marshal
    old, old_contract, old_binding = _reviewed_epoch_pipeline(old_raw)
    current, current_contract, current_binding = _reviewed_epoch_pipeline(current_raw)
    proofs = []
    projected = []
    method_names = {"encode", "decode", "pipeline_serialization", "binding_metadata", "_fast_backend"}
    for pipeline, raw_source, pins, live in ((old, sources["old_worker"], old_pins, False),
                                           (current, sources["current_worker"], current_pins, True)):
        body = _parse_json(_json_bytes(pipeline))
        worker_rows = [row for row in body["implementation"] if row.get("sha256") == pins["worker"]]
        _reviewed_epoch_need(len(worker_rows) == 1, "unique actual worker implementation row required")
        row = worker_rows[0]
        _reviewed_epoch_need(set(row) == {"path", "bytes", "sha256"}
            and row["bytes"] == len(raw_source), "worker implementation bytes differ")
        if live:
            _reviewed_epoch_need(row["path"] == str(Path(__file__)), "current tokenizer origin was retagged")
        compiled = compile(raw_source, row["path"], "exec", dont_inherit=True, optimize=0)
        cls = _reviewed_epoch_code(compiled, "ReviewedPretrainedTokenizer")
        methods = body["frontend"]["wrapper_methods"]
        _reviewed_epoch_need(type(methods) is dict and set(methods) == method_names,
            "complete maintained wrapper method identity required")
        method_hashes = {}
        for name in sorted(method_names):
            code = _reviewed_epoch_code(cls, name)
            digest = _digest(marshal.dumps(code, 2))
            offered = methods[name]
            _reviewed_epoch_need(type(offered) is dict and offered.get("code_sha256") == digest
                and offered.get("module") == __name__
                and offered.get("qualname") == "ReviewedPretrainedTokenizer." + name
                and offered.get("kind") == "python_code", "stored wrapper code differs from exact maintained source")
            if live:
                _reviewed_epoch_need(_digest(marshal.dumps(getattr(ReviewedPretrainedTokenizer, name).__code__, 2)) == digest,
                    "loaded wrapper code differs from current source")
            method_hashes[name] = digest
            offered["code_sha256"] = "authenticated-maintained-code-location"
        body["implementation"].remove(row)
        projected.append(body)
        proofs.append({"worker_origin": row, "wrapper_method_code_sha256": method_hashes})
    _reviewed_epoch_need(_json_bytes(projected[0]) == _json_bytes(projected[1]),
        "tokenizer backend/vocabulary/frontend/dependency/transport semantics changed")
    return {"old_contract": old_contract, "current_contract": current_contract,
        "old_binding": old_binding, "current_binding": current_binding, "method_proofs": proofs}

def _reviewed_epoch_dependencies(reference, old_manifest, old_config_sha, old_pipeline_sha, backend, *, _current_cache_contract=None):
    """Authenticate an explicit frozen pre-adoption dependency snapshot.

    This covers a fixed declared runtime set, not transitive-library attestation.
    Absence is a refusal; a caller boolean never substitutes for file identities.
    """
    import sys
    snapshot, _ = _reviewed_epoch_document(reference, limit=1024**2)
    if _current_cache_contract is None:
        fields = {"schema", "association_scope", "old_checkpoint_manifest_sha256", "old_configuration_sha256",
                  "old_tokenizer_pipeline_sha256", "old_source_sha256", "implementation"}
        _reviewed_epoch_need(type(snapshot) is dict and set(snapshot) == fields
            and snapshot["schema"] == "reviewed-decoder-migration-dependency-snapshot/v1"
            and snapshot["association_scope"] == "declared-current-cohort-before-Source-transition-not-historical-execution-attestation/v1"
            and snapshot["old_checkpoint_manifest_sha256"] == old_manifest["artifact_sha256"]
            and snapshot["old_configuration_sha256"] == old_config_sha
            and snapshot["old_tokenizer_pipeline_sha256"] == old_pipeline_sha
            and snapshot["old_source_sha256"] == old_manifest["producer_pins"],
            "frozen dependency snapshot does not bind the actual old pair/configuration")
    else:
        _reviewed_digest_cache_current_dependency_metadata(snapshot,old_manifest,old_config_sha,old_pipeline_sha,_current_cache_contract)
    modules = {"torch": "torch", "torch_native": "torch._C", "torch_serialization": "torch.serialization",
        "torch_optimizer_base": "torch.optim.optimizer", "model_class": type(backend.model).__module__,
        "model_config_class": type(backend.model.config).__module__, "optimizer_class": type(backend.optimizer).__module__,
        "transformers_modeling_utils": "transformers.modeling_utils"}
    rows = snapshot["implementation"]
    _reviewed_epoch_need(type(rows) is dict and set(rows) == set(modules)
        and sum(row["bytes"] for row in rows.values()) <= 64*1024**2,
        "complete bounded declared dependency set required")
    for role, module_name in modules.items():
        module = sys.modules.get(module_name)
        _reviewed_epoch_need(module is not None and rows[role]["path"] == str(Path(module.__file__)),
            "declared runtime dependency origin differs: " + role)
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(rows[role]), limit=16*1024**2, load=False)
    return snapshot

def _reviewed_epoch_prepare_binding(spec, registry, tokenizer, current_admission_provider):
    from ...logic.autoformal import training_cycle_inputs as inputs
    exposure_raw = _reviewed_decoder_artifact(spec.exposure_artifact)
    contexts_raw = _reviewed_decoder_artifact(spec.source_contexts_artifact)
    exposure, contexts = _parse_json(exposure_raw), _parse_json(contexts_raw)
    _reviewed_epoch_need(_json_bytes(exposure) == exposure_raw and _json_bytes(contexts) == contexts_raw,
        "exact canonical exposure/context inputs required")
    admission = current_admission_provider()
    return inputs.prepare_reviewed_mixed_decoder_training_inputs_v4(registry,
        admission_profile=spec.admission_profile, stage_artifact=asdict(spec.stage_artifact),
        expected_stage_sha256=spec.stage_artifact.sha256, current_admission_inputs=admission,
        expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,
        exposure_records=exposure, expected_exposure_sha256=spec.exposure_artifact.sha256,
        source_contexts=contexts, expected_source_contexts_sha256=spec.source_contexts_artifact.sha256,
        split_config=_thaw(spec.split_config), expected_split_config_sha256=spec.expected_split_config_sha256,
        tokenizer=tokenizer, max_source_tokens=spec.max_source_tokens,
        max_target_tokens=spec.max_target_tokens, allow_fictional_fixture=spec.allow_fictional_fixture)

def _reviewed_epoch_authenticate_assets(spec, backend):
    limit = backend._checkpoint_byte_limit()
    for item in (spec.model_artifact,spec.tokenizer_artifact,spec.license_artifact,*spec.backend_artifacts):
        _reviewed_decoder_artifact(item,limit=(limit if item is spec.model_artifact
            or item in spec.backend_artifacts else MAX_CHECKPOINT_BYTES),load=False)

def _reviewed_epoch_binding_proof(old, current, contract):
    _reviewed_epoch_need(type(old) is type(current) is dict and set(old) == set(current)
        and old.get("schema") == current.get("schema") == "reviewed-decoder-training-input-receipt/v4",
        "same complete V4 binding field set required")
    for field in set(old) - {"implementation", "tokenizer_contract"}:
        _reviewed_epoch_need(_json_bytes(old[field]) == _json_bytes(current[field]),
            "population, tokens, policy, provenance or admission changed: " + field)
    old_impl, current_impl = dict(old["implementation"]), dict(current["implementation"])
    old_input = [key for key,value in old_impl.items() if value == contract["old_source_sha256"]["inputs"]]
    current_input = [key for key,value in current_impl.items() if value == contract["current_source_sha256"]["inputs"]]
    _reviewed_epoch_need(len(old_input) == len(current_input) == 1, "unique maintained input producer identity required")
    old_impl.pop(old_input[0]);current_impl.pop(current_input[0])
    _reviewed_epoch_need(old_impl == current_impl, "unchanged input dependencies differ")

def _reviewed_epoch_backend_identity(configuration, worker_sha):
    return {"backend_id": "torch-complete-reviewed-decoder/v2:" + _digest(_json_bytes(configuration)),
        "implementation_sha256": worker_sha, "checkpoint_format": "torch-weights-only-complete-reviewed-state-pair/v2",
        "target_codec": "complete-reviewed-norm-json/v2", "source_conditioned": True,
        "pretrained": configuration["pretrained_declaration"]}

def _reviewed_epoch_old_pair(backend, model_raw, optimizer_raw, configuration, optimizer_steps):
    import io
    torch = backend._torch()
    _reviewed_epoch_need(all(type(raw) is bytes and 0 < len(raw) <= backend._checkpoint_byte_limit()
        for raw in (model_raw, optimizer_raw)), "bounded actual old pair required")
    model = torch.load(io.BytesIO(model_raw), map_location="cpu", weights_only=True)
    optimizer = torch.load(io.BytesIO(optimizer_raw), map_location="cpu", weights_only=True)
    signature = _digest(_json_bytes(configuration))
    _reviewed_epoch_need(type(model) is dict
        and set(model) == {"schema", "configuration_sha256", "state", "state_metadata"}
        and model["schema"] == "torch-reviewed-model-state/v2" and model["configuration_sha256"] == signature
        and type(model["state"]) is dict and type(model["state_metadata"]) is dict
        and type(optimizer) is dict
        and set(optimizer) == {"schema", "configuration_sha256", "state", "optimizer_steps", "cpu_rng", "device_rng"}
        and optimizer["schema"] == "torch-reviewed-optimizer-state/v1" and optimizer["configuration_sha256"] == signature
        and type(optimizer["state"]) is dict
        and type(optimizer["optimizer_steps"]) is int and optimizer["optimizer_steps"] == optimizer_steps
        and model["state_metadata"] == backend._model_state()["state_metadata"],
        "old halves, configuration, metadata or global step do not match")
    backend._finite_state(model);backend._finite_state(optimizer)
    _reviewed_epoch_need(torch.is_tensor(optimizer["cpu_rng"]) and optimizer["cpu_rng"].dtype == torch.uint8
        and optimizer["cpu_rng"].ndim == 1 and 0 < optimizer["cpu_rng"].numel() <= 1024**2
        and optimizer["device_rng"] is None and next(backend.model.parameters()).device.type == "cpu",
        "complete CPU RNG and CPU-only profile required")
    return model, optimizer

def _reviewed_epoch_pair_equal(backend, old_model, old_optimizer, current_model, current_optimizer):
    return (backend._same(old_model["state"], current_model["state"])
        and backend._same(old_model["state_metadata"], current_model["state_metadata"])
        and backend._same(old_optimizer["state"], current_optimizer["state"])
        and old_optimizer["optimizer_steps"] == current_optimizer["optimizer_steps"]
        and backend._same(old_optimizer["cpu_rng"], current_optimizer["cpu_rng"])
        and backend._same(old_optimizer["device_rng"], current_optimizer["device_rng"]))



def _reviewed_epoch_context(spec, old_configuration_artifact, old_tokenizer_pipeline_artifact,
                            current_configuration_artifact, compatibility_contract_artifact):
    _reviewed_epoch_need(type(spec) is ReviewedMixedDecoderTrainingJobSpec
        and spec.continuation_profile == REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE,
        "explicit mixed continuation job is required")
    contract_ref = asdict(compatibility_contract_artifact)
    contract, _ = _reviewed_epoch_document(contract_ref, limit=2*1024**2)
    _reviewed_epoch_need(type(contract) is dict and {"old_configuration_sha256",
        "current_configuration_sha256", "old_tokenizer_pipeline_sha256"} <= set(contract),
        "complete source compatibility contract required")
    old, old_raw = _reviewed_epoch_document(asdict(spec.parent_checkpoint_artifact), limit=4*1024**2)
    fields = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
        "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
        "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
    _reviewed_epoch_need(type(old) is dict and set(old) == fields
        and old["schema"] == REVIEWED_DECODER_CHECKPOINT_SCHEMA
        and old["qualified"] is False and old["promotion_performed"] is False,
        "first migration profile requires the complete original V1 manifest")
    _reviewed_epoch_need(old["model_state"] == asdict(spec.base_model_checkpoint)
        and old["optimizer_state"] == asdict(spec.base_optimizer_checkpoint)
        and old["checkpoint_lineage_id"] == spec.checkpoint_lineage_id
        and old["base_version_id"] == spec.base_version_id
        and type(old["batch_size"]) is int and old["batch_size"] == spec.batch_size
        and type(old["seed"]) is int and old["seed"] == spec.seed
        and old["assets"] == [asdict(item) for item in (spec.model_artifact,
            spec.tokenizer_artifact, spec.license_artifact, *spec.backend_artifacts)],
        "exact old numerical halves/lineage/assets/batch/seed required")
    binding, progress = old["training_binding"], old["progress"]
    _reviewed_epoch_need(type(binding) is dict and binding.get("schema") == "reviewed-decoder-training-input-receipt/v4"
        and binding.get("admission_profile") == spec.admission_profile
        and type(binding.get("record_count")) is int and 0 < binding["record_count"] <= 128
        and binding.get("stage_artifact_sha256") == spec.stage_artifact.sha256,
        "same nonempty original population and complete V4 binding required")
    _reviewed_epoch_need(type(progress) is dict
        and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
        and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values())
        and progress["optimizer_steps"] > 0 and progress["row_cursor"] < binding["record_count"]
        and progress["row_cursor"] % spec.batch_size == 0
        and progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(binding["record_count"]/spec.batch_size)
            + progress["row_cursor"]//spec.batch_size,
        "progressed original global/local counters required")
    old_config, old_config_raw = _reviewed_epoch_document(asdict(old_configuration_artifact), limit=4*1024**2)
    current_config, current_config_raw = _reviewed_epoch_document(asdict(current_configuration_artifact), limit=4*1024**2)
    old_pipeline_raw = _reviewed_decoder_artifact(old_tokenizer_pipeline_artifact,
        limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _, token_contract, token_binding = _reviewed_epoch_pipeline(old_pipeline_raw)
    _reviewed_epoch_need(contract["old_configuration_sha256"] == _digest(old_config_raw)
        and contract["current_configuration_sha256"] == _digest(current_config_raw)
        and contract["old_tokenizer_pipeline_sha256"] == _digest(old_pipeline_raw),
        "configuration or actual old pipeline capture differs")
    sources = _reviewed_epoch_sources(contract, old, spec)
    _reviewed_epoch_need(old_config.get("device") == current_config.get("device") == "cpu"
        and old_config.get("tokenizer") == token_contract and old_config.get("tokenizer_binding") == token_binding
        and old["backend_identity"] == _reviewed_epoch_backend_identity(old_config, contract["old_source_sha256"]["worker"])
        and _thaw(spec.backend_identity) == _reviewed_epoch_backend_identity(current_config, contract["current_source_sha256"]["worker"]),
        "old and current complete configurations/identities are not authenticated")
    _reviewed_epoch_need(old["token_budgets"] == {"max_source_tokens": spec.max_source_tokens,
        "max_target_tokens": spec.max_target_tokens, "tokenizer_contract": token_contract}
        and binding.get("tokenizer_contract") == token_contract,
        "old complete tokenizer contract or budgets differ")
    _reviewed_epoch_need(set(old_config) == set(current_config)
        and all(_json_bytes(old_config[key]) == _json_bytes(current_config[key])
                for key in old_config if key not in {"tokenizer", "tokenizer_binding"}),
        "architecture/parameter/buffer/dependency versions/optimizer settings changed")
    return {"spec": spec, "old_manifest": old, "old_manifest_raw": old_raw,
        "old_configuration": old_config, "current_configuration": current_config,
        "old_pipeline_raw": old_pipeline_raw, "contract": contract, "sources": sources,
        "old_configuration_artifact": asdict(old_configuration_artifact),
        "old_pipeline_artifact": asdict(old_tokenizer_pipeline_artifact),
        "current_configuration_artifact": asdict(current_configuration_artifact),
        "source_contract_artifact": contract_ref}

def _reviewed_epoch_restore(backend, model_raw, optimizer_raw, context, registry,
                            current_admission_provider, current):
    """Real state transfer, followed by ordinary current-format verification."""
    if type(context) is dict and context.get("profile") == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:
        return _reviewed_train_resume_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current)
    if type(context) is dict and context.get("profile") == REVIEWED_DECODER_READONLY_EPOCH_PROFILE:
        return _reviewed_readonly_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current)
    from collections import OrderedDict
    _reviewed_epoch_need(type(backend) is TorchReviewedDecoderBackend,
        "exact maintained Torch backend required")
    spec = context["spec"]
    # Even the private loader path recomputes the complete artifact-bound proof;
    # an arbitrary context dictionary is never a mismatch-acceptance switch.
    checked = _reviewed_epoch_context(spec,
        CheckpointArtifact.from_dict(context["old_configuration_artifact"]),
        CheckpointArtifact.from_dict(context["old_pipeline_artifact"]),
        CheckpointArtifact.from_dict(context["current_configuration_artifact"]),
        CheckpointArtifact.from_dict(context["source_contract_artifact"]))
    context.clear()
    context.update(checked)
    current()
    _reviewed_epoch_need(_json_bytes(backend._configuration()) == _json_bytes(context["current_configuration"]),
        "constructed current configuration differs")
    _reviewed_epoch_authenticate_assets(spec,backend)
    current_raw = backend.tokenizer.pipeline_serialization()
    proof = _reviewed_epoch_pipeline_proof(context["old_pipeline_raw"], current_raw,
        context["sources"], context["contract"]["old_source_sha256"],
        context["contract"]["current_source_sha256"])
    _reviewed_epoch_need(proof["current_contract"] == context["current_configuration"]["tokenizer"]
        and proof["current_binding"] == context["current_configuration"]["tokenizer_binding"],
        "actual current pipeline differs from configuration")
    snapshot = _reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
        {**context["old_manifest"], "artifact_sha256": spec.parent_checkpoint_artifact.sha256},
        context["contract"]["old_configuration_sha256"],
        context["contract"]["old_tokenizer_pipeline_sha256"], backend)
    prepared = _reviewed_epoch_prepare_binding(spec, registry, backend.tokenizer, current_admission_provider)
    _reviewed_epoch_binding_proof(context["old_manifest"]["training_binding"],
        prepared["receipt"], context["contract"])
    _reviewed_epoch_need(prepared["receipt"]["tokenizer_contract"] == proof["current_contract"],
        "ordinary current input preparation differs from current pipeline")
    current()
    model, optimizer = _reviewed_epoch_old_pair(backend, model_raw, optimizer_raw,
        context["old_configuration"], context["old_manifest"]["progress"]["optimizer_steps"])
    state = OrderedDict(model["state"])
    state._metadata = model["state_metadata"]
    backend.model.load_state_dict(state, strict=True)
    current()
    backend.optimizer.load_state_dict(optimizer["state"])
    current()
    backend._torch().set_rng_state(optimizer["cpu_rng"])
    backend._optimizer_steps = optimizer["optimizer_steps"]
    current()
    live_model = backend._model_state()
    live_optimizer = {"state": backend.optimizer.state_dict(), "optimizer_steps": backend._optimizer_steps,
        "cpu_rng": backend._torch().get_rng_state(), "device_rng": None}
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend, model, optimizer, live_model, live_optimizer),
        "actual model/Adam/RNG transfer was not bit preserving")
    derivative = backend.snapshot_checkpoint()
    verified_model, verified_optimizer = backend._load_pair(derivative["model_state"], derivative["optimizer_state"])
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend, model, optimizer, verified_model, verified_optimizer),
        "actual current-format derivative changed numerical state")
    current()
    _reviewed_epoch_need(backend.tokenizer.pipeline_serialization() == current_raw
        and _reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
            {**context["old_manifest"], "artifact_sha256": spec.parent_checkpoint_artifact.sha256},
            context["contract"]["old_configuration_sha256"],
            context["contract"]["old_tokenizer_pipeline_sha256"], backend) == snapshot,
        "pipeline/current dependency cohort changed during state transfer")
    context["current_pipeline_raw"] = current_raw
    context["current_training_binding"] = prepared["receipt"]
    context["pipeline_proof"] = proof
    context["derivative_pair"] = derivative
    context["dependency_scope"] = "declared_current_cohort_before_after_Source_transition_not_historical_execution_attestation"
    return derivative["model_state"], derivative["optimizer_state"]

def _reviewed_epoch_receipt_spec(receipt, old_manifest, backend):
    """Build only the immutable fields used to revalidate migration provenance."""
    spec_fields = receipt["target_job_spec"]
    spec = ReviewedMixedDecoderTrainingJobSpec.from_dict(spec_fields)
    _reviewed_epoch_need(type(backend) is TorchReviewedDecoderBackend
        and backend.identity() == _thaw(spec.backend_identity),
        "migration receipt requires its actual current backend")
    return spec

def _reviewed_epoch_validate_receipt(reference, backend, *, expected_spec=None):
    """Recompute source/semantic proof and compare BOTH actual initial pairs.

    This is deliberately bounded correctness work, not a cache or resource grant.
    Current candidate updates may differ; the frozen initial derivative remains
    the numerical witness for the Source transition.
    """
    receipt, _ = _reviewed_epoch_document(reference, limit=8*1024**2)
    if type(receipt) is dict and receipt.get("profile") == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:
        return _reviewed_train_resume_epoch_validate_receipt(reference, backend, expected_spec=expected_spec)
    fields = {"schema", "profile", "old_checkpoint_manifest", "old_configuration_artifact",
        "old_pipeline_artifact", "current_configuration_artifact", "source_contract_artifact",
        "current_pipeline_artifact", "derivative_model_checkpoint", "derivative_optimizer_checkpoint",
        "target_job_spec", "migrated_training_binding", "original_progress", "pipeline_proof",
        "source_projection_sha256", "dependency_scope", "historical_dependency_execution_requalified",
        "model_Adam_steps_RNG_and_progress_preserved", "qualified", "promotion_performed",
        "legal_meaning_verified", "convergence_proved", "corpus_admitted"}
    _reviewed_epoch_need(type(receipt) is dict and set(receipt) == fields
        and receipt["schema"] == REVIEWED_DECODER_SOURCE_EPOCH_RECEIPT_SCHEMA
        and receipt["profile"] == REVIEWED_DECODER_SOURCE_EPOCH_PROFILE
        and receipt["dependency_scope"] == "declared_current_cohort_before_after_Source_transition_not_historical_execution_attestation"
        and receipt["historical_dependency_execution_requalified"] is False
        and receipt["model_Adam_steps_RNG_and_progress_preserved"] is True
        and all(receipt[key] is False for key in ("qualified", "promotion_performed",
                "legal_meaning_verified", "convergence_proved", "corpus_admitted")),
        "closed non-authorizing migration receipt required")
    spec = _reviewed_epoch_receipt_spec(receipt, None, backend)
    _reviewed_epoch_need(asdict(spec.parent_checkpoint_artifact) == receipt["old_checkpoint_manifest"],
        "old manifest reference was replaced")
    if expected_spec is not None:
        _reviewed_epoch_need(spec.checkpoint_lineage_id == expected_spec.checkpoint_lineage_id
            and spec.base_version_id == expected_spec.base_version_id
            and spec.batch_size == expected_spec.batch_size and spec.seed == expected_spec.seed
            and spec.backend_identity == expected_spec.backend_identity
            and spec.expected_source_sha256 == expected_spec.expected_source_sha256
            and [asdict(item) for item in (spec.model_artifact,spec.tokenizer_artifact,spec.license_artifact,*spec.backend_artifacts)]
                == [asdict(item) for item in (expected_spec.model_artifact,expected_spec.tokenizer_artifact,expected_spec.license_artifact,*expected_spec.backend_artifacts)],
            "migration lineage/backend/assets/batch/seed differs")
    context = _reviewed_epoch_context(spec,
        CheckpointArtifact.from_dict(receipt["old_configuration_artifact"]),
        CheckpointArtifact.from_dict(receipt["old_pipeline_artifact"]),
        CheckpointArtifact.from_dict(receipt["current_configuration_artifact"]),
        CheckpointArtifact.from_dict(receipt["source_contract_artifact"]))
    _reviewed_epoch_authenticate_assets(spec,backend)
    current_raw = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["current_pipeline_artifact"]),
        limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _reviewed_epoch_need(current_raw == backend.tokenizer.pipeline_serialization(),
        "current pipeline changed after migration")
    proof = _reviewed_epoch_pipeline_proof(context["old_pipeline_raw"], current_raw, context["sources"],
        context["contract"]["old_source_sha256"], context["contract"]["current_source_sha256"])
    _reviewed_epoch_need(proof == receipt["pipeline_proof"]
        and receipt["source_projection_sha256"] == context["sources"]["projection_sha256"]
        and receipt["original_progress"] == context["old_manifest"]["progress"],
        "migration proof or original global/local progress changed")
    _reviewed_epoch_binding_proof(context["old_manifest"]["training_binding"],
        receipt["migrated_training_binding"], context["contract"])
    _reviewed_epoch_need(receipt["migrated_training_binding"]["tokenizer_contract"] == proof["current_contract"],
        "migrated binding pipeline differs")
    _reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
        {**context["old_manifest"],"artifact_sha256":spec.parent_checkpoint_artifact.sha256},
        context["contract"]["old_configuration_sha256"],
        context["contract"]["old_tokenizer_pipeline_sha256"], backend)
    limit = backend._checkpoint_byte_limit()
    old_model, old_optimizer = _reviewed_epoch_old_pair(backend,
        _reviewed_decoder_artifact(spec.base_model_checkpoint, limit=limit),
        _reviewed_decoder_artifact(spec.base_optimizer_checkpoint, limit=limit),
        context["old_configuration"], context["old_manifest"]["progress"]["optimizer_steps"])
    current_model, current_optimizer = backend._load_pair(
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["derivative_model_checkpoint"]), limit=limit),
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["derivative_optimizer_checkpoint"]), limit=limit))
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend,old_model,old_optimizer,current_model,current_optimizer),
        "old/initial-derivative numerical halves, Adam or RNG differ")
    return receipt

def migrate_local_reviewed_decoder_source_epoch_v3(spec, *, registry, current_admission_provider,
        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,
        tokenizer_artifact, license_artifact, old_configuration_artifact,
        old_tokenizer_pipeline_artifact, current_configuration_artifact,
        compatibility_contract_artifact, output_directory, max_model_bytes,
        runtime_profile="builtin-t5-gpt2-float32/v1"):
    """Explicitly migrate one progressed V1 pair to the qualified current epoch.

    Actual old pipeline and current dependency-cohort snapshots must be captured
    BEFORE Source adoption. No fresh vendor import, fitting, counter/RNG reset,
    old-artifact rewrite, promotion or historical dependency requalification.
    The caller retains existing execution/resource/asset/admission ownership.
    """
    import gc
    import stat
    _reviewed_epoch_need(all(callable(value) for value in
        (current_admission_provider,execution_guard,asset_policy_guard)), "existing live guards required")
    _reviewed_epoch_need(type(spec) is ReviewedMixedDecoderTrainingJobSpec
        and tokenizer_artifact == spec.tokenizer_artifact and license_artifact == spec.license_artifact
        and recipe_artifact in spec.backend_artifacts and model_config_artifact in spec.backend_artifacts
        and recipe_artifact != model_config_artifact,
        "loader recipe/configuration/tokenizer/license must be the exact declared old assets")
    execution_guard()
    policy = {"schema":"reviewed-decoder-source-epoch-migration-policy/v1",
        "target_job_spec":spec.to_dict(), "old_configuration":asdict(old_configuration_artifact),
        "old_pipeline":asdict(old_tokenizer_pipeline_artifact),
        "current_configuration":asdict(current_configuration_artifact),
        "source_contract":asdict(compatibility_contract_artifact),
        "migration_requested":True, "training_requested":False,"downloads_requested":False,
        "resource_grant_requested":False,"promotion_requested":False}
    asset_policy_guard(_parse_json(_json_bytes(policy)))
    context = _reviewed_epoch_context(spec,old_configuration_artifact,old_tokenizer_pipeline_artifact,
        current_configuration_artifact,compatibility_contract_artifact)
    output = Path(output_directory)
    _reviewed_epoch_need(output.is_absolute() and not os.path.lexists(output)
        and output.parent.resolve(strict=True)==output.parent
        and output != Path(spec.output_directory)
        and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in output.parents),
        "distinct fresh ordinary migration output directory required")
    import torch
    entry_rng = torch.get_rng_state().clone()
    succeeded = False
    try:
        runtime, internal_receipt = _load_local_reviewed_decoder_runtime(
            registry=registry,current_admission_provider=current_admission_provider,
            execution_guard=execution_guard,asset_policy_guard=asset_policy_guard,
            recipe_artifact=recipe_artifact,model_config_artifact=model_config_artifact,
            tokenizer_artifact=tokenizer_artifact,license_artifact=license_artifact,
            model_checkpoint=spec.base_model_checkpoint,optimizer_checkpoint=spec.base_optimizer_checkpoint,
            expected_backend_identity=_thaw(spec.backend_identity),
            expected_source_sha256=_thaw(spec.expected_source_sha256),
            expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,
            max_model_bytes=max_model_bytes,_admission_version="v3",_runtime_profile=runtime_profile,
            _source_epoch_migration=context)
        execution_guard()
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(
            context["derivative_pair"]["model_state"],context["derivative_pair"]["optimizer_state"]),
            "current pair changed before publication")
        output.mkdir(mode=0o700,exist_ok=False)
        model = _write_exclusive(output/"model.checkpoint",context["derivative_pair"]["model_state"])
        optimizer = _write_exclusive(output/"optimizer.checkpoint",context["derivative_pair"]["optimizer_state"])
        pipeline = _write_exclusive(output/"current-tokenizer-pipeline.json",context["current_pipeline_raw"])
        receipt = {"schema":REVIEWED_DECODER_SOURCE_EPOCH_RECEIPT_SCHEMA,
            "profile":REVIEWED_DECODER_SOURCE_EPOCH_PROFILE,
            "old_checkpoint_manifest":asdict(spec.parent_checkpoint_artifact),
            "old_configuration_artifact":context["old_configuration_artifact"],
            "old_pipeline_artifact":context["old_pipeline_artifact"],
            "current_configuration_artifact":context["current_configuration_artifact"],
            "source_contract_artifact":context["source_contract_artifact"],
            "current_pipeline_artifact":pipeline,"derivative_model_checkpoint":model,
            "derivative_optimizer_checkpoint":optimizer,"target_job_spec":spec.to_dict(),
            "migrated_training_binding":context["current_training_binding"],
            "original_progress":context["old_manifest"]["progress"],
            "pipeline_proof":context["pipeline_proof"],
            "source_projection_sha256":context["sources"]["projection_sha256"],
            "dependency_scope":context["dependency_scope"],
            "historical_dependency_execution_requalified":False,
            "model_Adam_steps_RNG_and_progress_preserved":True,
            "qualified":False,"promotion_performed":False,"legal_meaning_verified":False,
            "convergence_proved":False,"corpus_admitted":False}
        receipt_ref = _write_exclusive(output/"source-epoch-migration.json",_json_bytes(receipt))
        original = context["old_manifest"]
        manifest = {**original,"schema":REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA,
            "backend_identity":_thaw(spec.backend_identity),
            "producer_pins":_thaw(spec.expected_source_sha256),
            "training_binding":context["current_training_binding"],
            "model_state":model,"optimizer_state":optimizer,
            "token_budgets":{"max_source_tokens":spec.max_source_tokens,"max_target_tokens":spec.max_target_tokens,
                "tokenizer_contract":context["current_training_binding"]["tokenizer_contract"]},
            "parent_checkpoint_sha256":spec.parent_checkpoint_artifact.sha256,
            "continuation_profile":spec.continuation_profile,"optimizer_step_offset":0,
            "stage_continuation":None,"source_epoch_migration":receipt_ref}
        manifest_ref = _write_exclusive(output/"reviewed-decoder-checkpoint.json",_json_bytes(manifest))
        # Drop the first live model before the genuinely ordinary current loader
        # constructs another. It sees only current-format derivative artifacts.
        del runtime
        context.pop("derivative_pair")
        gc.collect()
        runtime, load_receipt = load_local_reviewed_decoder_runtime_v3(
            admission_profile=spec.admission_profile,registry=registry,
            current_admission_provider=current_admission_provider,execution_guard=execution_guard,
            asset_policy_guard=asset_policy_guard,recipe_artifact=recipe_artifact,
            model_config_artifact=model_config_artifact,tokenizer_artifact=tokenizer_artifact,
            license_artifact=license_artifact,model_checkpoint=CheckpointArtifact.from_dict(model),
            optimizer_checkpoint=CheckpointArtifact.from_dict(optimizer),
            expected_backend_identity=_thaw(spec.backend_identity),
            expected_source_sha256=_thaw(spec.expected_source_sha256),
            expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,
            max_model_bytes=max_model_bytes,runtime_profile=runtime_profile)
        _reviewed_epoch_validate_receipt(receipt_ref,runtime.backend,expected_spec=spec)
        prepared = _reviewed_epoch_prepare_binding(spec,registry,runtime.tokenizer,current_admission_provider)
        _reviewed_epoch_need(prepared["receipt"] == context["current_training_binding"],
            "ordinary current admission/input binding changed after derivative reload")
        new_spec = spec.to_dict()
        new_spec.update(parent_checkpoint_artifact=manifest_ref,
            base_model_checkpoint=model,base_optimizer_checkpoint=optimizer)
        result = {"schema":"reviewed-decoder-source-epoch-migration-operation/v1",
            "migration_receipt":receipt_ref,"candidate":manifest_ref,
            "model_checkpoint":model,"optimizer_checkpoint":optimizer,"next_job_spec":new_spec,
            "worker_progress":dict(original["progress"]),"ordinary_current_loader":load_receipt,
            "qualified":False,"promotion_performed":False,"training_performed":False,
            "resource_granted":False,"historical_dependency_execution_requalified":False}
        execution_guard()
        _reviewed_epoch_validate_receipt(receipt_ref,runtime.backend,expected_spec=spec)
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(model),limit=runtime.backend._checkpoint_byte_limit()),
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(optimizer),limit=runtime.backend._checkpoint_byte_limit())),
            "live derivative pair changed during final callback/provenance validation")
        _reviewed_epoch_need(runtime.backend.identity()==_thaw(spec.backend_identity)
            and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile)==_thaw(spec.expected_source_sha256),
            "current backend or Source changed before migration publication")
        _write_exclusive(output/"receipt.json",_json_bytes(result))
        directory_fd=os.open(output,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        succeeded=True
        return runtime,result
    except BaseException as error:
        if output.exists():
            try:_write_exclusive(output/"failure.json",_json_bytes({
                "schema":"reviewed-decoder-source-epoch-migration-failure/v1",
                "error_type":type(error).__name__,"partial_output_preserved":True,
                "old_artifacts_rewritten":False,"qualified":False,"promotion_performed":False}))
            except BaseException as publication_error:
                error.add_note("failed to retain migration failure metadata: "+type(publication_error).__name__)
        raise
    finally:
        if not succeeded:torch.set_rng_state(entry_rng)

__all__ += ["migrate_local_reviewed_decoder_source_epoch_v3", "REVIEWED_DECODER_SOURCE_EPOCH_PROFILE",
            "REVIEWED_DECODER_SOURCE_EPOCH_CONTRACT_SCHEMA", "REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA"]


REVIEWED_DECODER_READONLY_EPOCH_PROFILE = "9dcd7d6b-to-counts-factored-readonly/v1"
REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA = "reviewed-decoder-readonly-refactor-compatibility/v1"
REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA = "reviewed-decoder-readonly-refactor-migration/v1"
REVIEWED_DECODER_READONLY_EPOCH_CHECKPOINT_SCHEMA = "reviewed-decoder-readonly-refactor-checkpoint/v1"
REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA = "reviewed-decoder-pristine-pair-migration-origin/v1"
REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER = "9dcd7d6b57dee43f562d45dc22672a1c1a3004802e94849a289ec813a8d62236"
REVIEWED_DECODER_READONLY_EPOCH_OLD_INPUTS = "a6883078a59ca6e3a5ae9a5fc69da5b43d1d513a3701a1d9dfe2c38b714d7049"



def _reviewed_readonly_epoch_projection(old_raw, current_raw):
    """Mechanically undo only the reviewed Python counts/shared numerical refactor.

    Bridge definitions are the closed named implementation of this profile;
    they are still bound by the complete current worker SHA/live Source pins.
    No archived source is executed. The extra buffer restoration verification
    is recorded explicitly: projection equivalence is the projected Qwen path.
    """
    import ast
    import copy
    _reviewed_epoch_need(type(old_raw) is type(current_raw) is bytes
        and REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER == '9dcd7d6b57dee43f562d45dc22672a1c1a3004802e94849a289ec813a8d62236'
        and _digest(old_raw) == REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER,
        "exact original9d Source body required")
    dump = lambda node: ast.dump(node, include_attributes=False)
    statement = lambda text: ast.parse(text).body[0]
    old, current = ast.parse(old_raw), ast.parse(current_raw)
    def definitions(body):
        rows = [node for node in body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
        _reviewed_epoch_need(len({node.name for node in rows}) == len(rows), "duplicate Source definition")
        return {node.name: node for node in rows}
    old_defs, current_defs = definitions(old.body), definitions(current.body)
    bridge_names = {
        '_reviewed_readonly_epoch_projection', '_reviewed_readonly_epoch_sources',
        '_reviewed_readonly_epoch_context', '_reviewed_readonly_epoch_restore',
        '_reviewed_readonly_epoch_validate_receipt',
        'migrate_local_reviewed_decoder_readonly_source_epoch_v4',
        '_reviewed_readonly_epoch_operational_receipt'} | {'migrate_local_reviewed_decoder_train_resume_source_epoch_v5', '_reviewed_train_resume_epoch_restore', '_reviewed_train_resume_epoch_validate_receipt', '_reviewed_train_resume_epoch_sources', '_reviewed_train_resume_epoch_context'}
    _reviewed_epoch_need(set(current_defs) == set(old_defs) | bridge_names | {'_expected_teacher_forced_position_counts'},
        "unsupported top-level refactor definition")
    expected_ast = {'_preserve_readonly_state': '93b10a8c365d92111c50bd58a2b201416b101a4e1d2d5eb393b5d4120b6a5c99', '_teacher_forced_forward': '9731e3401fcd814e07b5d2da863fa49c5ad94513f9af4b4ea6f4efd5ca6a9b65', 'teacher_forced_fit_batch': '8d65dc61dfbc623afe370d37df082052985fcc7cc7a316af0910851641b2f93e', '_expected_teacher_forced_position_counts': 'f722b5579685ae5465652333af9390819445d4ed5abe23e05c72d8f32bca33f0'}
    _reviewed_epoch_need(_digest(dump(current_defs['_reviewed_readonly_epoch_operational_receipt']).encode())
        == '15457d70de1abf1594d236b9c3a7435ec329fc8878eecd15405769410d607a4e', 'classified operational receipt helper changed')
    train_bridge_hashes = {'_reviewed_train_resume_epoch_sources': '09ecf1af5eb8ee1c34e19367da7e71ef9bdceca982885ced7186504179bfd395', '_reviewed_train_resume_epoch_context': 'ec06bc63a2fc4a49960bdb359b6561aedefe6357ee2e0a42095573394a441f61', '_reviewed_train_resume_epoch_restore': 'c3822e312a729015dd52e2712042e4834f5590354aecce6f0e21541b539a4914', '_reviewed_train_resume_epoch_validate_receipt': 'cbf826d91418031fe8f763b1946712346dded2e949f7efc78e9ad9e2b810cb13', 'migrate_local_reviewed_decoder_train_resume_source_epoch_v5': 'dd39e27dfa3123363f1bb384ce64f36a7ca7b2edbb0dd7019e81037c153bbfae'}
    for name, expected in train_bridge_hashes.items():
        _reviewed_epoch_need(_digest(dump(current_defs[name]).encode()) == expected,
            "closed TRAIN-resume bridge implementation changed: " + name)
    preserved_readonly_bridge_hashes = {'_reviewed_readonly_epoch_sources': 'b5ecd864196b29631d40ea3266bbdf3eb4d8931ec6b590be7e956d3d600ad62e', '_reviewed_readonly_epoch_context': '54f1dc921d8db364d69ec843d8cea6f42613cce4289b18e623bfb84ec339f330', '_reviewed_readonly_epoch_restore': 'bc1b290dc2df5c67f1d07f0e44b88c08a2d9219ed8177bd5fd4df64b43d4e008', '_reviewed_readonly_epoch_validate_receipt': 'b091e6956e195c005aaa2fc5388643c3c2647b3bd6bbbf924db7ca78b697ce15', 'migrate_local_reviewed_decoder_readonly_source_epoch_v4': '0e7f731721ef2375c18d5a0f69ea9804d1326f028c6cd0e4b99ee4e43088e837', '_reviewed_readonly_epoch_operational_receipt': '15457d70de1abf1594d236b9c3a7435ec329fc8878eecd15405769410d607a4e'}
    for name, expected in preserved_readonly_bridge_hashes.items():
        _reviewed_epoch_need(_digest(dump(current_defs[name]).encode()) == expected,
            "preserved readonly bridge implementation changed: " + name)
    backend = current_defs['TorchReviewedDecoderBackend']
    old_backend = old_defs['TorchReviewedDecoderBackend']
    methods, old_methods = definitions(backend.body), definitions(old_backend.body)
    additions = {'_preserve_readonly_state', '_teacher_forced_forward', 'teacher_forced_fit_batch'}
    _reviewed_epoch_need(set(methods) == set(old_methods) | additions,
        "unsupported backend method addition or deletion")
    for name in additions:
        _reviewed_epoch_need(_digest(dump(methods[name]).encode()) == expected_ast[name],
            "reviewed readonly/shared helper changed: " + name)
    _reviewed_epoch_need(_digest(dump(current_defs['_expected_teacher_forced_position_counts']).encode())
        == expected_ast['_expected_teacher_forced_position_counts'], "declared count geometry changed")
    # Undo the exact additive report allowlist, not arbitrary report processing.
    union = ast.parse("{'loss','gradient_norm','optimizer_steps','trainable_parameter_count','gradient_parameter_count'} | set(_EXPECTED_TEACHER_FORCED_COUNT_KEYS)", mode='eval').body
    class Reports(ast.NodeTransformer):
        count = 0
        def visit_BinOp(self, node):
            if dump(node) == dump(union):
                self.count += 1
                return copy.deepcopy(node.left)
            return self.generic_visit(node)
    reports = Reports()
    current_defs['_execute_reviewed_decoder_job'] = reports.visit(current_defs['_execute_reviewed_decoder_job'])
    _reviewed_epoch_need(reports.count == 1, "exact additive count report allowlist required")
    # Re-inline the one unchanged teacher-forced forward. Only declared Python
    # count statements can disappear; labels, model calls and optimizer math stay.
    train = methods['train_batch']
    removals = [statement("expected_counts = dict.fromkeys(_EXPECTED_TEACHER_FORCED_COUNT_KEYS, 0)"),
        statement("row_counts = _expected_teacher_forced_position_counts(len(source), len(target), encoder_decoder=self.architecture == 'encoder_decoder', prompt_length=None if framed is None else len(framed[index]))"),
        statement("for key, count in row_counts.items():\n expected_counts[key] += count"),
        statement("result.update(expected_counts)")]
    removed = [0] * len(removals)
    forward_call = statement("output = self._teacher_forced_forward(source, target, torch=torch, device=device, prompt=None if framed is None else framed[index])")
    helper = methods['_teacher_forced_forward']
    _reviewed_epoch_need(len(helper.body) == 3 and isinstance(helper.body[1], ast.If)
        and dump(helper.body[-1]) == dump(statement('return output')), "closed shared forward required")
    forward = copy.deepcopy(helper.body[1])
    _reviewed_epoch_need(len(forward.orelse) == 1 and isinstance(forward.orelse[0], ast.If)
        and dump(forward.orelse[0].test) == dump(ast.parse('prompt is not None', mode='eval').body),
        "closed framed forward branch required")
    forward.orelse[0].test = ast.parse('framed is not None', mode='eval').body
    forward.orelse[0].body.insert(0, statement('prompt = framed[index]'))
    class Training(ast.NodeTransformer):
        calls = 0
        def visit(self, node):
            if isinstance(node, ast.stmt):
                for index, expected in enumerate(removals):
                    if dump(node) == dump(expected):
                        removed[index] += 1
                        return None
                if dump(node) == dump(forward_call):
                    self.calls += 1
                    return copy.deepcopy(forward)
            return super().visit(node)
    training = Training()
    methods['train_batch'] = training.visit(train)
    _reviewed_epoch_need(removed == [1,1,1,1] and training.calls == 1
        and dump(methods['train_batch']) == dump(old_methods['train_batch']),
        "training forward/math/labels/conditioning changed after exact reinlining")
    # Re-inline capture and the finally restoration from the shared context.
    generate = methods['generate_batch']
    contexts = [(index,node) for index,node in enumerate(generate.body)
        if isinstance(node,ast.With) and len(node.items)==1
        and dump(node.items[0].context_expr)==dump(ast.parse(
            'self._preserve_readonly_state(projected_model=projected_model)', mode='eval').body)]
    _reviewed_epoch_need(len(contexts)==1 and contexts[0][0]==len(generate.body)-1,
        "one closed generation context required")
    position, context = contexts[0]
    _reviewed_epoch_need(type(context.items[0].optional_vars) is ast.Name
        and dump(context.items[0].optional_vars)==dump(ast.Name(id='readonly_state',ctx=ast.Store())),
        "exact readonly_state context header binding required")
    _reviewed_epoch_need(dump(context.body[0])==dump(statement(
        'device, owner_identity, original_owner_identity = readonly_state')),
        "generation context binding changed")
    capture = methods['_preserve_readonly_state']
    prelude = [statement('import copy'),statement('from collections import OrderedDict'),
        statement('torch = self._torch()'),statement('model_owner, optimizer_owner = self.model, self.optimizer')]
    _reviewed_epoch_need(len(capture.body)>6 and all(dump(a)==dump(b) for a,b in
        zip(capture.body[1:5],prelude,strict=True)), "shared capture imports/owners changed")
    restoration = copy.deepcopy(capture.body[-1])
    _reviewed_epoch_need(isinstance(restoration,ast.Try) and not restoration.handlers and not restoration.orelse
        and len(restoration.body)==1 and isinstance(restoration.body[0],ast.Expr)
        and isinstance(restoration.body[0].value,ast.Yield)
        and dump(restoration.body[0].value.value)==dump(ast.parse(
            '(device, owner_identity, original_owner_identity)', mode='eval').body),
        "shared capture yield/finally changed")
    captured = copy.deepcopy(capture.body[5:-1])
    _reviewed_epoch_need(dump(captured[0])==dump(statement(
        'llama_buffers = tuple((value, value.detach().clone()) for _, value in model_owner.named_buffers())')),
        "reviewed complete buffer capture changed")
    # For the ONLY supported CPU BF16 Qwen profile projected_model is true.
    # The generic snapshot was strengthened; do not assert generic equivalence.
    captured[0].value = ast.IfExp(test=ast.Name(id='projected_model',ctx=ast.Load()),
        body=captured[0].value,orelse=ast.Tuple(elts=[],ctx=ast.Load()))
    extra_check = ast.parse('all(self._same(value, saved) for value, saved in llama_buffers)', mode='eval').body
    class Verification(ast.NodeTransformer):
        count = 0
        def visit_BoolOp(self,node):
            values = []
            for value in node.values:
                if dump(value)==dump(extra_check):self.count+=1
                else:values.append(self.visit(value))
            node.values=values
            return node
    verification=Verification()
    restoration=verification.visit(restoration)
    _reviewed_epoch_need(verification.count==1, "explicit additional buffer restoration verification changed")
    restoration.body=copy.deepcopy(context.body[1:])
    generate.body=generate.body[:position]+captured+[restoration]
    _reviewed_epoch_need(dump(generate)==dump(old_methods['generate_batch']),
        "generation body/capture/finally changed after exact reinlining")
    backend.body=[methods.get(node.name,node) if isinstance(node,(ast.FunctionDef,ast.ClassDef)) else node
        for node in backend.body if not isinstance(node,(ast.FunctionDef,ast.ClassDef)) or node.name not in additions]
    # Two existing family hook changes are exact dispatches. Their old route
    # remains literally the original body after removing this new branch.
    restore=current_defs['_reviewed_epoch_restore']
    train_dispatch=statement("if type(context) is dict and context.get('profile') == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:\n return _reviewed_train_resume_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current)")
    _reviewed_epoch_need(dump(restore.body[1])==dump(train_dispatch),"exact TRAIN-resume restoration dispatch required")
    restore.body.pop(1)
    receipt_validate=current_defs['_reviewed_epoch_validate_receipt']
    train_receipt_dispatch=statement("if type(receipt) is dict and receipt.get('profile') == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:\n return _reviewed_train_resume_epoch_validate_receipt(reference, backend, expected_spec=expected_spec)")
    _reviewed_epoch_need(dump(receipt_validate.body[2])==dump(train_receipt_dispatch),"exact TRAIN-resume receipt dispatch required")
    receipt_validate.body.pop(2)
    dispatch=statement("if type(context) is dict and context.get('profile') == REVIEWED_DECODER_READONLY_EPOCH_PROFILE:\n return _reviewed_readonly_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current)")
    _reviewed_epoch_need(dump(restore.body[1])==dump(dispatch), "exact readonly restoration dispatch required")
    restore.body.pop(1)
    old_policy=ast.parse('REVIEWED_DECODER_SOURCE_EPOCH_PROFILE',mode='eval').body
    new_policy=ast.parse("REVIEWED_DECODER_READONLY_EPOCH_PROFILE if type(_source_epoch_migration) is dict and _source_epoch_migration.get('profile') == REVIEWED_DECODER_READONLY_EPOCH_PROFILE else REVIEWED_DECODER_SOURCE_EPOCH_PROFILE",mode='eval').body
    class Loader(ast.NodeTransformer):
        count=0
        def visit_IfExp(self,node):
            if dump(node)==dump(new_policy):self.count+=1;return copy.deepcopy(old_policy)
            return self.generic_visit(node)
    train_policy=ast.parse("REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE if type(_source_epoch_migration) is dict and _source_epoch_migration.get('profile') == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE else (REVIEWED_DECODER_READONLY_EPOCH_PROFILE if type(_source_epoch_migration) is dict and _source_epoch_migration.get('profile') == REVIEWED_DECODER_READONLY_EPOCH_PROFILE else REVIEWED_DECODER_SOURCE_EPOCH_PROFILE)",mode='eval').body
    class TrainPolicy(ast.NodeTransformer):
        count=0
        def visit_IfExp(self,node):
            if dump(node)==dump(train_policy):self.count+=1;return copy.deepcopy(new_policy)
            return self.generic_visit(node)
    train_loader=TrainPolicy();current_defs['_load_local_reviewed_decoder_runtime']=train_loader.visit(current_defs['_load_local_reviewed_decoder_runtime'])
    _reviewed_epoch_need(train_loader.count==1,"exact TRAIN-resume policy dispatch required")
    loader=Loader();current_defs['_load_local_reviewed_decoder_runtime']=loader.visit(current_defs['_load_local_reviewed_decoder_runtime'])
    _reviewed_epoch_need(loader.count==1, "exact new-profile asset-policy dispatch required")
    allowed_constants={
        'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE':'9dcd7d6b-to-counts-factored-TRAIN-resume/v1',
        'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_CONTRACT_SCHEMA':'reviewed-decoder-train-refactor-compatibility/v1',
        'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA':'reviewed-decoder-train-refactor-migration/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_PROFILE':'9dcd7d6b-to-counts-factored-readonly/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA':'reviewed-decoder-readonly-refactor-compatibility/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA':'reviewed-decoder-readonly-refactor-migration/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_CHECKPOINT_SCHEMA':'reviewed-decoder-readonly-refactor-checkpoint/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA':'reviewed-decoder-pristine-pair-migration-origin/v1',
        'REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER':'9dcd7d6b57dee43f562d45dc22672a1c1a3004802e94849a289ec813a8d62236',
        'REVIEWED_DECODER_READONLY_EPOCH_OLD_INPUTS':'a6883078a59ca6e3a5ae9a5fc69da5b43d1d513a3701a1d9dfe2c38b714d7049'}
    allowed_export=statement("__all__ += ['migrate_local_reviewed_decoder_readonly_source_epoch_v4', 'REVIEWED_DECODER_READONLY_EPOCH_PROFILE', 'REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_CHECKPOINT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA']")
    allowed_train_export=statement("__all__ += ['migrate_local_reviewed_decoder_train_resume_source_epoch_v5', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_CONTRACT_SCHEMA', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA']")
    normalized=[];constants=set();exports=0;count_keys=0;train_exports=0
    for node in current.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)):
            if node.name in bridge_names or node.name=='_expected_teacher_forced_position_counts':continue
            normalized.append(current_defs[node.name]);continue
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name in allowed_constants:
                _reviewed_epoch_need(isinstance(node.value,ast.Constant) and node.value.value==allowed_constants[name],
                    'literal readonly bridge constant required')
                constants.add(name);continue
            if name=='_EXPECTED_TEACHER_FORCED_COUNT_KEYS':
                _reviewed_epoch_need(ast.literal_eval(node.value)==('expected_record_count', 'expected_input_positions', 'expected_raw_label_positions', 'expected_raw_ignored_positions', 'expected_target_body_eos_positions', 'expected_aligned_nonignored_positions', 'expected_aligned_ignored_positions'),
                    'declared Python count keys changed')
                count_keys+=1;continue
        if dump(node)==dump(allowed_export):exports+=1;continue
        if dump(node)==dump(allowed_train_export):train_exports+=1;continue
        normalized.append(node)
    _reviewed_epoch_need(constants==set(allowed_constants) and exports==1 and train_exports==1 and count_keys==1
        and dump(ast.Module(body=normalized,type_ignores=[]))==dump(old),
        'unrelated numerical/tokenizer/global/Source changes are unsupported')
    return {'rule':'exact9d-shared-forward-capture-finally-reinlining-count-metadata-only/v1',
        'old_worker_sha256':_digest(old_raw),'current_worker_sha256':_digest(current_raw),
        'numerical_projection_sha256':_digest(dump(old).encode()),
        'buffer_scope':'projected CPU BF16 Qwen2 snapshot identical; extra all-buffer restoration verification explicitly retained',
        'generic_nonprojected_equivalence_claimed':False,
        'count_metadata_is_observed_NLL':False,'old_source_executed':False}



def _reviewed_readonly_epoch_sources(contract, origin, spec):
    """Current physical Source proof for the explicit old9d readonly refactor."""
    from ...logic.autoformal import training_cycle_inputs as inputs
    fields = {"schema", "profile", "old_checkpoint_manifest_sha256", "old_configuration_sha256",
        "current_configuration_sha256", "old_tokenizer_pipeline_sha256", "old_source_sha256",
        "current_source_sha256", "old_source_artifacts", "current_source_artifacts",
        "dependency_snapshot_artifact", "old_training_binding_artifact"}
    _reviewed_epoch_need(type(contract) is dict and set(contract)==fields
        and contract["schema"]==REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA
        and contract["profile"]==REVIEWED_DECODER_READONLY_EPOCH_PROFILE,
        "closed readonly-refactor compatibility contract required")
    old_pins, current_pins=contract["old_source_sha256"],contract["current_source_sha256"]
    _reviewed_epoch_need(type(old_pins)is type(current_pins)is dict
        and set(old_pins)==set(current_pins)==REVIEWED_DECODER_SOURCE_NAMES
        and contract["old_checkpoint_manifest_sha256"]==spec.parent_checkpoint_artifact.sha256
        and old_pins==origin["producer_pins"] and current_pins==_thaw(spec.expected_source_sha256)
        and old_pins["worker"]==REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER
        and old_pins["inputs"]==current_pins["inputs"]==REVIEWED_DECODER_READONLY_EPOCH_OLD_INPUTS
        and all(old_pins[key]==current_pins[key]for key in ("consumer","admission","splits"))
        and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile)==current_pins,
        "unsupported readonly-refactor Source5 or changed common producer")
    old_refs,new_refs=contract["old_source_artifacts"],contract["current_source_artifacts"]
    _reviewed_epoch_need(type(old_refs)is type(new_refs)is dict and set(old_refs)==set(new_refs)=={"worker","inputs"},
        "exact old/current worker and input artifacts required")
    old_raw,new_raw={},{}
    for role in ("worker","inputs"):
        old_raw[role]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(old_refs[role]),limit=2*1024**2)
        new_raw[role]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(new_refs[role]),limit=2*1024**2)
        _reviewed_epoch_need(_digest(old_raw[role])==old_pins[role]and _digest(new_raw[role])==current_pins[role],
            "readonly-refactor Source artifact hash differs")
    _reviewed_epoch_need(Path(new_refs["worker"]["path"])==Path(__file__)
        and Path(new_refs["inputs"]["path"])==Path(inputs.__file__)
        and old_raw["inputs"]==new_raw["inputs"],"current physical origin or unchanged inputs differ")
    projection=_reviewed_readonly_epoch_projection(old_raw["worker"],new_raw["worker"])
    return {"old_worker":old_raw["worker"],"current_worker":new_raw["worker"],
        "old_inputs":old_raw["inputs"],"current_inputs":new_raw["inputs"],
        "projection_sha256":projection["numerical_projection_sha256"],"readonly_projection":projection}


def _reviewed_readonly_epoch_operational_receipt(reference, *, receipt_kind):
    """Read only the two byte-authenticated pristine operational evidence roles.

    Import/independent-restore observations are ordinary JSON, not canonical
    normative profile documents. Original references, bytes and hashes remain
    authoritative; the existing pristine origin checks still join every used
    pair/backend/Source/progress fact. This reader creates no restored state
    and is never used by old v3 or by Source/config/contract/checkpoint profiles.
    """
    _reviewed_epoch_need(receipt_kind in {"prepared_pair", "independent_restoration"},
        "classified pristine operational receipt role required")
    raw = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(reference), limit=4*1024**2)
    value = _parse_json(raw)
    _reviewed_epoch_need(type(value) is dict, "classified pristine operational receipt object required")
    return value, raw


def _reviewed_readonly_epoch_context(spec, old_configuration_artifact, old_tokenizer_pipeline_artifact,
        current_configuration_artifact, compatibility_contract_artifact):
    """Two honest origins: actual V1 trained3 or newly declared pristine0 metadata."""
    _reviewed_epoch_need(type(spec)is ReviewedMixedDecoderTrainingJobSpec
        and spec.continuation_profile==REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE,
        "explicit bounded mixed-domain migration spec required")
    contract_ref=asdict(compatibility_contract_artifact)
    contract,_=_reviewed_epoch_document(contract_ref,limit=2*1024**2)
    _reviewed_epoch_need(type(contract)is dict and {"schema","profile","old_training_binding_artifact",
        "old_configuration_sha256","current_configuration_sha256","old_tokenizer_pipeline_sha256"}<=set(contract)
        and contract["schema"]==REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA
        and contract["profile"]==REVIEWED_DECODER_READONLY_EPOCH_PROFILE,
        "explicit readonly-refactor compatibility contract required")
    origin,origin_raw=_reviewed_epoch_document(asdict(spec.parent_checkpoint_artifact),limit=4*1024**2)
    common={"schema","checkpoint_lineage_id","base_version_id","backend_identity","assets",
        "training_binding","model_state","optimizer_state","progress","batch_size","seed",
        "parent_checkpoint_sha256","producer_pins","token_budgets","qualified","promotion_performed"}
    _reviewed_epoch_need(type(origin)is dict,"explicit original paired-state metadata required")
    pristine=origin.get("schema")==REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA
    _reviewed_epoch_need(set(origin)==common|({"origin_evidence_artifacts"}if pristine else set())
        and origin["schema"]in {REVIEWED_DECODER_CHECKPOINT_SCHEMA,REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA}
        and origin["qualified"]is False and origin["promotion_performed"]is False,
        "original trained V1 or explicitly new pristine migration-origin metadata required")
    if pristine:
        evidence=origin["origin_evidence_artifacts"]
        _reviewed_epoch_need(type(evidence)is dict and set(evidence)=={"prepared_pair","independent_restoration"},
            "pristine origin must retain actual import/strict-restore metadata references")
        prepared_pair,_=_reviewed_readonly_epoch_operational_receipt(
            evidence["prepared_pair"],receipt_kind="prepared_pair")
        strict_restore,_=_reviewed_readonly_epoch_operational_receipt(
            evidence["independent_restoration"],receipt_kind="independent_restoration")
        _reviewed_epoch_need(type(prepared_pair)is type(strict_restore)is dict
            and type(prepared_pair.get("artifacts"))is dict and type(strict_restore.get("loader_receipt"))is dict
            and prepared_pair.get("optimizer_steps")==0 and type(prepared_pair.get("optimizer_steps"))is int
            and prepared_pair.get("artifacts",{}).get("model_checkpoint")==origin["model_state"]
            and prepared_pair.get("artifacts",{}).get("optimizer_checkpoint")==origin["optimizer_state"]
            and prepared_pair.get("expected_backend_identity")==origin["backend_identity"]
            and prepared_pair.get("expected_source_sha256")==origin["producer_pins"]
            and strict_restore.get("prepared_pair")==evidence["prepared_pair"]
            and strict_restore.get("canonical_configuration_bytes_equal")is True
            and strict_restore.get("training_performed")is False
            and strict_restore.get("loader_receipt",{}).get("matched_pair")is True
            and strict_restore["loader_receipt"].get("checkpoint_restored")is True
            and type(strict_restore["loader_receipt"].get("optimizer_steps"))is int
            and strict_restore["loader_receipt"].get("optimizer_steps")==0,
            "pristine origin import/independent-restore pair and Source identities do not join")
        _reviewed_epoch_need(origin["training_binding"]is None and origin["parent_checkpoint_sha256"]is None,
            "pristine origin cannot claim prior training or a progressed candidate")
    _reviewed_epoch_need(origin["model_state"]==asdict(spec.base_model_checkpoint)
        and origin["optimizer_state"]==asdict(spec.base_optimizer_checkpoint)
        and origin["checkpoint_lineage_id"]==spec.checkpoint_lineage_id
        and origin["base_version_id"]==spec.base_version_id
        and type(origin["batch_size"])is int and origin["batch_size"]==spec.batch_size==1
        and type(origin["seed"])is int and origin["seed"]==spec.seed
        and origin["assets"]==[asdict(item)for item in(spec.model_artifact,spec.tokenizer_artifact,
            spec.license_artifact,*spec.backend_artifacts)],"exact old numeric pair/origin/assets required")
    progress=origin["progress"]
    expected={"epochs_completed":0,"row_cursor":0,"optimizer_steps":0}if pristine else {
        "epochs_completed":1,"row_cursor":0,"optimizer_steps":3}
    _reviewed_epoch_need(type(progress)is dict and progress==expected
        and all(type(value)is int for value in progress.values()),
        "readonly bridge supports exactly pristine0 or completed three-row TRAIN3")
    population,_=_reviewed_epoch_document(contract["old_training_binding_artifact"],limit=4*1024**2)
    _reviewed_epoch_need(type(population)is dict
        and population.get("schema")=="reviewed-decoder-training-input-receipt/v4"
        and population.get("admission_profile")==spec.admission_profile
        and population.get("record_count")==3 and type(population.get("record_count"))is int
        and population.get("stage_artifact_sha256")==spec.stage_artifact.sha256
        and type(population.get("training_record_ids"))is list and len(population["training_record_ids"])==3,
        "same exact prospective three-TRAIN-row V4 population required")
    if not pristine:_reviewed_epoch_need(origin["training_binding"]==population,"trained origin T3 binding differs")
    old_config,old_config_raw=_reviewed_epoch_document(asdict(old_configuration_artifact),limit=4*1024**2)
    current_config,current_config_raw=_reviewed_epoch_document(asdict(current_configuration_artifact),limit=4*1024**2)
    _reviewed_epoch_need(type(old_config)is type(current_config)is dict,"complete old/current configuration objects required")
    old_pipeline=_reviewed_decoder_artifact(old_tokenizer_pipeline_artifact,limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _,token_contract,token_binding=_reviewed_epoch_pipeline(old_pipeline)
    _reviewed_epoch_need(contract["old_configuration_sha256"]==_digest(old_config_raw)
        and contract["current_configuration_sha256"]==_digest(current_config_raw)
        and contract["old_tokenizer_pipeline_sha256"]==_digest(old_pipeline),"exact old/new config or captured9d pipeline differs")
    if pristine:_reviewed_epoch_need(prepared_pair.get("configuration_identity")==old_config,
        "pristine prepared-pair complete configuration differs")
    sources=_reviewed_readonly_epoch_sources(contract,origin,spec)
    _reviewed_epoch_need(old_config.get("device")==current_config.get("device")=="cpu"
        and old_config.get("model_profile")==current_config.get("model_profile")=="builtin-qwen2-bfloat16/v1"
        and old_config.get("model_class")==current_config.get("model_class")=="transformers.models.qwen2.modeling_qwen2.Qwen2ForCausalLM"
        and old_config.get("architecture")==current_config.get("architecture")=="causal_lm"
        and old_config.get("tokenizer")==token_contract and old_config.get("tokenizer_binding")==token_binding
        and origin["backend_identity"]==_reviewed_epoch_backend_identity(old_config,contract["old_source_sha256"]["worker"])
        and _thaw(spec.backend_identity)==_reviewed_epoch_backend_identity(current_config,contract["current_source_sha256"]["worker"]),
        "exact CPU BF16 Qwen old/current configurations and identities required")
    _reviewed_epoch_need(origin["token_budgets"]=={"max_source_tokens":spec.max_source_tokens,
        "max_target_tokens":spec.max_target_tokens,"tokenizer_contract":token_contract}
        and population.get("tokenizer_contract")==token_contract,
        "same old population token geometry and complete contract required")
    _reviewed_epoch_need(set(old_config)==set(current_config)
        and all(_json_bytes(old_config[key])==_json_bytes(current_config[key])
            for key in old_config if key not in {"tokenizer","tokenizer_binding"}),
        "model math/precision/conditioning/optimizer/configuration changed")
    version_key=_digest(_json_bytes({"old_origin":spec.parent_checkpoint_artifact.sha256,
        "current_source":contract["current_source_sha256"],
        "population":contract["old_training_binding_artifact"]["sha256"]}))
    new_lineage="readonly-source-epoch:"+version_key
    new_version="readonly-source-version:"+version_key
    _reviewed_epoch_need(new_lineage!=origin["checkpoint_lineage_id"]and new_version!=origin["base_version_id"],
        "new current lineage/version required; old IDs cannot be retagged")
    return {"profile":REVIEWED_DECODER_READONLY_EPOCH_PROFILE,"spec":spec,
        "old_manifest":origin,"old_manifest_raw":origin_raw,"origin_kind":"pristine0"if pristine else"trained3",
        "old_population_binding":population,"old_configuration":old_config,
        "current_configuration":current_config,"old_pipeline_raw":old_pipeline,
        "contract":contract,"sources":sources,"old_configuration_artifact":asdict(old_configuration_artifact),
        "old_pipeline_artifact":asdict(old_tokenizer_pipeline_artifact),
        "current_configuration_artifact":asdict(current_configuration_artifact),
        "source_contract_artifact":contract_ref,"new_checkpoint_lineage_id":new_lineage,
        "new_base_version_id":new_version}


def _reviewed_readonly_epoch_restore(backend,model_raw,optimizer_raw,context,registry,current_admission_provider,current):
    """Existing paired transfer with exact equality, new proof, no numeric updates."""
    from collections import OrderedDict
    _reviewed_epoch_need(type(backend)is TorchReviewedDecoderBackend,"exact current backend required")
    spec=context["spec"]
    checked=_reviewed_readonly_epoch_context(spec,
        CheckpointArtifact.from_dict(context["old_configuration_artifact"]),
        CheckpointArtifact.from_dict(context["old_pipeline_artifact"]),
        CheckpointArtifact.from_dict(context["current_configuration_artifact"]),
        CheckpointArtifact.from_dict(context["source_contract_artifact"]))
    context.clear();context.update(checked);current()
    _reviewed_epoch_need(_json_bytes(backend._configuration())==_json_bytes(context["current_configuration"]),
        "constructed readonly current configuration differs")
    _reviewed_epoch_authenticate_assets(spec,backend)
    current_raw=backend.tokenizer.pipeline_serialization()
    proof=_reviewed_epoch_pipeline_proof(context["old_pipeline_raw"],current_raw,context["sources"],
        context["contract"]["old_source_sha256"],context["contract"]["current_source_sha256"])
    _reviewed_epoch_need(proof["current_contract"]==context["current_configuration"]["tokenizer"]
        and proof["current_binding"]==context["current_configuration"]["tokenizer_binding"],
        "actual new pipeline/config identity differs")
    dependency=_reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
        {**context["old_manifest"],"artifact_sha256":spec.parent_checkpoint_artifact.sha256},
        context["contract"]["old_configuration_sha256"],context["contract"]["old_tokenizer_pipeline_sha256"],backend)
    prepared=_reviewed_epoch_prepare_binding(spec,registry,backend.tokenizer,current_admission_provider)
    _reviewed_epoch_binding_proof(context["old_population_binding"],prepared["receipt"],context["contract"])
    _reviewed_epoch_need(prepared["receipt"]["tokenizer_contract"]==proof["current_contract"],"current same-T3 input preparation differs")
    current()
    model,optimizer=_reviewed_epoch_old_pair(backend,model_raw,optimizer_raw,context["old_configuration"],context["old_manifest"]["progress"]["optimizer_steps"])
    _reviewed_epoch_need(bool(optimizer["state"]["state"])==(context["origin_kind"]=="trained3"),
        "pristine must have empty Adam; trained3 must retain actual nonempty Adam")
    state=OrderedDict(model["state"]);state._metadata=model["state_metadata"]
    backend.model.load_state_dict(state,strict=True);current()
    backend.optimizer.load_state_dict(optimizer["state"]);current()
    backend._torch().set_rng_state(optimizer["cpu_rng"]);backend._optimizer_steps=optimizer["optimizer_steps"];current()
    live_model=backend._model_state()
    live_optimizer={"state":backend.optimizer.state_dict(),"optimizer_steps":backend._optimizer_steps,
        "cpu_rng":backend._torch().get_rng_state(),"device_rng":None}
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend,model,optimizer,live_model,live_optimizer),
        "readonly bridge actual model/Adam/RNG transfer differs")
    derivative=backend.snapshot_checkpoint()
    new_model,new_optimizer=backend._load_pair(derivative["model_state"],derivative["optimizer_state"])
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend,model,optimizer,new_model,new_optimizer),
        "readonly new-format pair changed actual numerical halves or progress")
    current()
    _reviewed_epoch_need(backend.tokenizer.pipeline_serialization()==current_raw
        and _reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
            {**context["old_manifest"],"artifact_sha256":spec.parent_checkpoint_artifact.sha256},
            context["contract"]["old_configuration_sha256"],context["contract"]["old_tokenizer_pipeline_sha256"],backend)==dependency,
        "current pipeline/runtime cohort changed during transfer")
    context.update(current_pipeline_raw=current_raw,current_training_binding=prepared["receipt"],
        pipeline_proof=proof,derivative_pair=derivative,
        dependency_scope="declared_current_cohort_before_after_Source_transition_not_historical_execution_attestation")
    return derivative["model_state"],derivative["optimizer_state"]


def _reviewed_readonly_epoch_validate_receipt(reference,backend,*,expected_spec=None):
    """Recompute every proof and actual old/current pair; no receipt-only waiver."""
    receipt,_=_reviewed_epoch_document(reference,limit=8*1024**2)
    fields={"schema","profile","old_checkpoint_manifest","old_configuration_artifact","old_pipeline_artifact",
        "current_configuration_artifact","source_contract_artifact","current_pipeline_artifact",
        "derivative_model_checkpoint","derivative_optimizer_checkpoint","target_job_spec","migrated_training_binding",
        "original_progress","pipeline_proof","source_projection_sha256","dependency_scope",
        "historical_dependency_execution_requalified","model_Adam_steps_RNG_and_progress_preserved",
        "qualified","promotion_performed","legal_meaning_verified","convergence_proved","corpus_admitted",
        "new_checkpoint_lineage_id","new_base_version_id","origin_kind","readonly_only"}
    _reviewed_epoch_need(type(receipt)is dict and set(receipt)==fields
        and receipt["schema"]==REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA
        and receipt["profile"]==REVIEWED_DECODER_READONLY_EPOCH_PROFILE and receipt["readonly_only"]is True
        and receipt["historical_dependency_execution_requalified"]is False
        and receipt["model_Adam_steps_RNG_and_progress_preserved"]is True
        and all(receipt[key]is False for key in("qualified","promotion_performed","legal_meaning_verified","convergence_proved","corpus_admitted")),
        "closed nonauthorizing readonly migration receipt required")
    spec=_reviewed_epoch_receipt_spec(receipt,None,backend)
    if expected_spec is not None:_reviewed_epoch_need(spec.to_dict()==expected_spec.to_dict(),"readonly migration target spec changed")
    _reviewed_epoch_need(asdict(spec.parent_checkpoint_artifact)==receipt["old_checkpoint_manifest"],"readonly original pair metadata changed")
    context=_reviewed_readonly_epoch_context(spec,
        CheckpointArtifact.from_dict(receipt["old_configuration_artifact"]),
        CheckpointArtifact.from_dict(receipt["old_pipeline_artifact"]),
        CheckpointArtifact.from_dict(receipt["current_configuration_artifact"]),
        CheckpointArtifact.from_dict(receipt["source_contract_artifact"]))
    _reviewed_epoch_need(receipt["new_checkpoint_lineage_id"]==context["new_checkpoint_lineage_id"]
        and receipt["new_base_version_id"]==context["new_base_version_id"]
        and receipt["origin_kind"]==context["origin_kind"]
        and receipt["original_progress"]==context["old_manifest"]["progress"]
        and receipt["dependency_scope"]=="declared_current_cohort_before_after_Source_transition_not_historical_execution_attestation",
        "readonly lineage/version/original progress/scope differs")
    _reviewed_epoch_authenticate_assets(spec,backend)
    _reviewed_epoch_need(_json_bytes(backend._configuration())==_json_bytes(context["current_configuration"]),"readonly live complete config changed")
    current_raw=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["current_pipeline_artifact"]),limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _reviewed_epoch_need(current_raw==backend.tokenizer.pipeline_serialization(),"new actual tokenizer pipeline changed")
    proof=_reviewed_epoch_pipeline_proof(context["old_pipeline_raw"],current_raw,context["sources"],
        context["contract"]["old_source_sha256"],context["contract"]["current_source_sha256"])
    _reviewed_epoch_need(proof==receipt["pipeline_proof"]and receipt["source_projection_sha256"]==context["sources"]["projection_sha256"],"readonly pipeline/Source proof differs")
    _reviewed_epoch_binding_proof(context["old_population_binding"],receipt["migrated_training_binding"],context["contract"])
    _reviewed_epoch_need(receipt["migrated_training_binding"]["tokenizer_contract"]==proof["current_contract"],"readonly new population pipeline differs")
    _reviewed_epoch_dependencies(context["contract"]["dependency_snapshot_artifact"],
        {**context["old_manifest"],"artifact_sha256":spec.parent_checkpoint_artifact.sha256},
        context["contract"]["old_configuration_sha256"],context["contract"]["old_tokenizer_pipeline_sha256"],backend)
    limit=backend._checkpoint_byte_limit()
    old_model,old_optimizer=_reviewed_epoch_old_pair(backend,
        _reviewed_decoder_artifact(spec.base_model_checkpoint,limit=limit),
        _reviewed_decoder_artifact(spec.base_optimizer_checkpoint,limit=limit),context["old_configuration"],
        context["old_manifest"]["progress"]["optimizer_steps"])
    _reviewed_epoch_need(bool(old_optimizer["state"]["state"])==(context["origin_kind"]=="trained3"),"readonly old Adam origin mismatch")
    new_model,new_optimizer=backend._load_pair(
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["derivative_model_checkpoint"]),limit=limit),
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt["derivative_optimizer_checkpoint"]),limit=limit))
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend,old_model,old_optimizer,new_model,new_optimizer),
        "readonly actual old/new model/Adam/RNG/progress differ")
    return receipt


def migrate_local_reviewed_decoder_readonly_source_epoch_v4(spec,*,registry,current_admission_provider,
        execution_guard,asset_policy_guard,recipe_artifact,model_config_artifact,tokenizer_artifact,
        license_artifact,old_configuration_artifact,old_tokenizer_pipeline_artifact,
        current_configuration_artifact,compatibility_contract_artifact,output_directory,max_model_bytes,
        runtime_profile="builtin-qwen2-bfloat16/v1"):
    """Exact old9d pristine0/trained3 pairs to NEW readonly current versions.

    The caller owns actual execution/Source/resource/asset/admission custody.
    This creates no training/corpus/proof authority, resets no numeric counters,
    and never changes old12/14 bytes or identities. Normal current paired reload
    and independent actual pair equality are mandatory before success.
    """
    import gc
    import stat
    _reviewed_epoch_need(runtime_profile=="builtin-qwen2-bfloat16/v1"
        and all(callable(value)for value in(current_admission_provider,execution_guard,asset_policy_guard)),
        "existing live readonly Qwen load guards required")
    _reviewed_epoch_need(type(spec)is ReviewedMixedDecoderTrainingJobSpec
        and tokenizer_artifact==spec.tokenizer_artifact and license_artifact==spec.license_artifact
        and recipe_artifact in spec.backend_artifacts and model_config_artifact in spec.backend_artifacts
        and recipe_artifact!=model_config_artifact,"exact old asset declarations required")
    execution_guard()
    asset_policy_guard({"schema":"reviewed-decoder-source-epoch-migration-policy/v1",
        "profile":REVIEWED_DECODER_READONLY_EPOCH_PROFILE,"target_job_spec":spec.to_dict(),
        "old_configuration":asdict(old_configuration_artifact),"old_pipeline":asdict(old_tokenizer_pipeline_artifact),
        "current_configuration":asdict(current_configuration_artifact),"source_contract":asdict(compatibility_contract_artifact),
        "migration_requested":True,"readonly_only":True,"training_requested":False,"downloads_requested":False,
        "resource_grant_requested":False,"promotion_requested":False})
    context=_reviewed_readonly_epoch_context(spec,old_configuration_artifact,old_tokenizer_pipeline_artifact,
        current_configuration_artifact,compatibility_contract_artifact)
    output=Path(output_directory)
    _reviewed_epoch_need(output.is_absolute()and not os.path.lexists(output)
        and output.parent.resolve(strict=True)==output.parent and output!=Path(spec.output_directory)
        and all(stat.S_ISDIR(parent.lstat().st_mode)for parent in output.parents),"distinct fresh ordinary readonly migration output required")
    import torch
    entry_rng=torch.get_rng_state().clone();succeeded=False
    try:
        runtime,internal_receipt=_load_local_reviewed_decoder_runtime(registry=registry,
            current_admission_provider=current_admission_provider,execution_guard=execution_guard,
            asset_policy_guard=asset_policy_guard,recipe_artifact=recipe_artifact,
            model_config_artifact=model_config_artifact,tokenizer_artifact=tokenizer_artifact,
            license_artifact=license_artifact,model_checkpoint=spec.base_model_checkpoint,
            optimizer_checkpoint=spec.base_optimizer_checkpoint,expected_backend_identity=_thaw(spec.backend_identity),
            expected_source_sha256=_thaw(spec.expected_source_sha256),
            expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,max_model_bytes=max_model_bytes,
            _admission_version="v3",_runtime_profile=runtime_profile,_source_epoch_migration=context)
        execution_guard()
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(context["derivative_pair"]["model_state"],context["derivative_pair"]["optimizer_state"]),"readonly current pair changed before publication")
        output.mkdir(mode=0o700,exist_ok=False)
        model=_write_exclusive(output/"model.checkpoint",context["derivative_pair"]["model_state"])
        optimizer=_write_exclusive(output/"optimizer.checkpoint",context["derivative_pair"]["optimizer_state"])
        pipeline=_write_exclusive(output/"current-tokenizer-pipeline.json",context["current_pipeline_raw"])
        receipt={"schema":REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA,"profile":REVIEWED_DECODER_READONLY_EPOCH_PROFILE,
            "old_checkpoint_manifest":asdict(spec.parent_checkpoint_artifact),"old_configuration_artifact":context["old_configuration_artifact"],
            "old_pipeline_artifact":context["old_pipeline_artifact"],"current_configuration_artifact":context["current_configuration_artifact"],
            "source_contract_artifact":context["source_contract_artifact"],"current_pipeline_artifact":pipeline,
            "derivative_model_checkpoint":model,"derivative_optimizer_checkpoint":optimizer,"target_job_spec":spec.to_dict(),
            "migrated_training_binding":context["current_training_binding"],"original_progress":context["old_manifest"]["progress"],
            "pipeline_proof":context["pipeline_proof"],"source_projection_sha256":context["sources"]["projection_sha256"],
            "dependency_scope":context["dependency_scope"],"historical_dependency_execution_requalified":False,
            "model_Adam_steps_RNG_and_progress_preserved":True,"qualified":False,"promotion_performed":False,
            "legal_meaning_verified":False,"convergence_proved":False,"corpus_admitted":False,
            "new_checkpoint_lineage_id":context["new_checkpoint_lineage_id"],"new_base_version_id":context["new_base_version_id"],
            "origin_kind":context["origin_kind"],"readonly_only":True}
        receipt_ref=_write_exclusive(output/"source-epoch-readonly-migration.json",_json_bytes(receipt))
        origin=context["old_manifest"]
        manifest={"schema":REVIEWED_DECODER_READONLY_EPOCH_CHECKPOINT_SCHEMA,
            "checkpoint_lineage_id":context["new_checkpoint_lineage_id"],"base_version_id":context["new_base_version_id"],
            "backend_identity":_thaw(spec.backend_identity),"producer_pins":_thaw(spec.expected_source_sha256),
            "assets":origin["assets"],"model_state":model,"optimizer_state":optimizer,"progress":origin["progress"],
            "original_checkpoint_metadata":asdict(spec.parent_checkpoint_artifact),"original_lineage_id":origin["checkpoint_lineage_id"],
            "original_base_version_id":origin["base_version_id"],"original_origin_kind":context["origin_kind"],
            "diagnostic_TRAIN_population_binding":context["current_training_binding"],"source_epoch_migration":receipt_ref,
            "readonly_only":True,"training_performed":False,"qualified":False,"promotion_performed":False}
        manifest_ref=_write_exclusive(output/"readonly-reviewed-decoder-checkpoint.json",_json_bytes(manifest))
        del runtime;context.pop("derivative_pair");gc.collect()
        runtime,load_receipt=load_local_reviewed_decoder_runtime_v3(admission_profile=spec.admission_profile,registry=registry,
            current_admission_provider=current_admission_provider,execution_guard=execution_guard,
            asset_policy_guard=asset_policy_guard,recipe_artifact=recipe_artifact,model_config_artifact=model_config_artifact,
            tokenizer_artifact=tokenizer_artifact,license_artifact=license_artifact,
            model_checkpoint=CheckpointArtifact.from_dict(model),optimizer_checkpoint=CheckpointArtifact.from_dict(optimizer),
            expected_backend_identity=_thaw(spec.backend_identity),expected_source_sha256=_thaw(spec.expected_source_sha256),
            expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,max_model_bytes=max_model_bytes,runtime_profile=runtime_profile)
        _reviewed_readonly_epoch_validate_receipt(receipt_ref,runtime.backend,expected_spec=spec)
        prepared=_reviewed_epoch_prepare_binding(spec,registry,runtime.tokenizer,current_admission_provider)
        _reviewed_epoch_need(prepared["receipt"]==context["current_training_binding"],"current readonly T3 binding changed after reload")
        execution_guard()
        _reviewed_readonly_epoch_validate_receipt(receipt_ref,runtime.backend,expected_spec=spec)
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(model),limit=runtime.backend._checkpoint_byte_limit()),
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(optimizer),limit=runtime.backend._checkpoint_byte_limit()))
            and runtime.backend.identity()==_thaw(spec.backend_identity)
            and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile)==_thaw(spec.expected_source_sha256),
            "readonly live pair/Source changed during final callbacks")
        result={"schema":"reviewed-decoder-readonly-source-epoch-migration-operation/v1",
            "migration_receipt":receipt_ref,"candidate":manifest_ref,"model_checkpoint":model,"optimizer_checkpoint":optimizer,
            "new_checkpoint_lineage_id":context["new_checkpoint_lineage_id"],"new_base_version_id":context["new_base_version_id"],
            "worker_progress":dict(origin["progress"]),"ordinary_current_loader":load_receipt,
            "same_T3_diagnostic_binding":context["current_training_binding"],"readonly_only":True,
            "qualified":False,"promotion_performed":False,"training_performed":False,"resource_granted":False,
            "historical_dependency_execution_requalified":False}
        _write_exclusive(output/"receipt.json",_json_bytes(result))
        directory_fd=os.open(output,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        succeeded=True;return runtime,result
    except BaseException as error:
        if output.exists():
            try:_write_exclusive(output/"failure.json",_json_bytes({"schema":"reviewed-decoder-readonly-source-epoch-migration-failure/v1",
                "error_type":type(error).__name__,"partial_output_preserved":True,"old_artifacts_rewritten":False,
                "qualified":False,"promotion_performed":False}))
            except BaseException as publication_error:error.add_note("readonly migration failure metadata unavailable: "+type(publication_error).__name__)
        raise
    finally:
        if not succeeded:torch.set_rng_state(entry_rng)


__all__ += ['migrate_local_reviewed_decoder_readonly_source_epoch_v4', 'REVIEWED_DECODER_READONLY_EPOCH_PROFILE', 'REVIEWED_DECODER_READONLY_EPOCH_CONTRACT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_RECEIPT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_CHECKPOINT_SCHEMA', 'REVIEWED_DECODER_READONLY_EPOCH_PRISTINE_SCHEMA']


# Explicit original-TRAIN3 continuation across the exact reviewed refactor.
REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE = "9dcd7d6b-to-counts-factored-TRAIN-resume/v1"
REVIEWED_DECODER_TRAIN_RESUME_EPOCH_CONTRACT_SCHEMA = "reviewed-decoder-train-refactor-compatibility/v1"
REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA = "reviewed-decoder-train-refactor-migration/v1"


def _reviewed_train_resume_epoch_sources(contract, origin, spec):
    """Current physical Source proof for the explicit old9d TRAIN-resume refactor."""
    from ...logic.autoformal import training_cycle_inputs as inputs
    fields = {"schema", "profile", "old_checkpoint_manifest_sha256", "old_configuration_sha256",
        "current_configuration_sha256", "old_tokenizer_pipeline_sha256", "old_source_sha256",
        "current_source_sha256", "old_source_artifacts", "current_source_artifacts",
        "dependency_snapshot_artifact", "old_training_binding_artifact"}
    _reviewed_epoch_need(type(contract) is dict and set(contract)==fields
        and contract["schema"]==REVIEWED_DECODER_TRAIN_RESUME_EPOCH_CONTRACT_SCHEMA
        and contract["profile"]==REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE,
        "closed TRAIN-resume-refactor compatibility contract required")
    old_pins, current_pins=contract["old_source_sha256"],contract["current_source_sha256"]
    _reviewed_epoch_need(type(old_pins)is type(current_pins)is dict
        and set(old_pins)==set(current_pins)==REVIEWED_DECODER_SOURCE_NAMES
        and contract["old_checkpoint_manifest_sha256"]==spec.parent_checkpoint_artifact.sha256
        and old_pins==origin["producer_pins"] and current_pins==_thaw(spec.expected_source_sha256)
        and old_pins["worker"]==REVIEWED_DECODER_READONLY_EPOCH_OLD_WORKER
        and old_pins["inputs"]==current_pins["inputs"]==REVIEWED_DECODER_READONLY_EPOCH_OLD_INPUTS
        and all(old_pins[key]==current_pins[key]for key in ("consumer","admission","splits"))
        and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile)==current_pins,
        "unsupported TRAIN-resume-refactor Source5 or changed common producer")
    old_refs,new_refs=contract["old_source_artifacts"],contract["current_source_artifacts"]
    _reviewed_epoch_need(type(old_refs)is type(new_refs)is dict and set(old_refs)==set(new_refs)=={"worker","inputs"},
        "exact old/current worker and input artifacts required")
    old_raw,new_raw={},{}
    for role in ("worker","inputs"):
        old_raw[role]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(old_refs[role]),limit=2*1024**2)
        new_raw[role]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(new_refs[role]),limit=2*1024**2)
        _reviewed_epoch_need(_digest(old_raw[role])==old_pins[role]and _digest(new_raw[role])==current_pins[role],
            "TRAIN-resume-refactor Source artifact hash differs")
    _reviewed_epoch_need(Path(new_refs["worker"]["path"])==Path(__file__)
        and Path(new_refs["inputs"]["path"])==Path(inputs.__file__)
        and old_raw["inputs"]==new_raw["inputs"],"current physical origin or unchanged inputs differ")
    projection=_reviewed_readonly_epoch_projection(old_raw["worker"],new_raw["worker"])
    return {"old_worker":old_raw["worker"],"current_worker":new_raw["worker"],
        "old_inputs":old_raw["inputs"],"current_inputs":new_raw["inputs"],
        "projection_sha256":projection["numerical_projection_sha256"],"readonly_projection":projection}

def _reviewed_train_resume_epoch_context(spec, old_configuration_artifact, old_tokenizer_pipeline_artifact,
                            current_configuration_artifact, compatibility_contract_artifact):
    _reviewed_epoch_need(type(spec) is ReviewedMixedDecoderTrainingJobSpec
        and spec.continuation_profile == REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE,
        "explicit mixed continuation job is required")
    contract_ref = asdict(compatibility_contract_artifact)
    contract, _ = _reviewed_epoch_document(contract_ref, limit=2*1024**2)
    _reviewed_epoch_need(type(contract) is dict and {"old_configuration_sha256",
        "current_configuration_sha256", "old_tokenizer_pipeline_sha256"} <= set(contract),
        "complete source compatibility contract required")
    old, old_raw = _reviewed_epoch_document(asdict(spec.parent_checkpoint_artifact), limit=4*1024**2)
    fields = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
        "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
        "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
    _reviewed_epoch_need(type(old) is dict and set(old) == fields
        and old["schema"] == REVIEWED_DECODER_CHECKPOINT_SCHEMA
        and old["qualified"] is False and old["promotion_performed"] is False,
        "first migration profile requires the complete original V1 manifest")
    _reviewed_epoch_need(old["model_state"] == asdict(spec.base_model_checkpoint)
        and old["optimizer_state"] == asdict(spec.base_optimizer_checkpoint)
        and old["checkpoint_lineage_id"] == spec.checkpoint_lineage_id
        and old["base_version_id"] == spec.base_version_id
        and type(old["batch_size"]) is int and old["batch_size"] == spec.batch_size
        and type(old["seed"]) is int and old["seed"] == spec.seed
        and old["assets"] == [asdict(item) for item in (spec.model_artifact,
            spec.tokenizer_artifact, spec.license_artifact, *spec.backend_artifacts)],
        "exact old numerical halves/lineage/assets/batch/seed required")
    binding, progress = old["training_binding"], old["progress"]
    _reviewed_epoch_need(type(binding) is dict and binding.get("schema") == "reviewed-decoder-training-input-receipt/v4"
        and binding.get("admission_profile") == spec.admission_profile
        and type(binding.get("record_count")) is int and 0 < binding["record_count"] <= 128
        and binding.get("stage_artifact_sha256") == spec.stage_artifact.sha256,
        "same nonempty original population and complete V4 binding required")
    _reviewed_epoch_need(type(progress) is dict
        and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
        and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values())
        and progress["optimizer_steps"] > 0 and progress["row_cursor"] < binding["record_count"]
        and progress["row_cursor"] % spec.batch_size == 0
        and progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(binding["record_count"]/spec.batch_size)
            + progress["row_cursor"]//spec.batch_size,
        "progressed original global/local counters required")
    _reviewed_epoch_need(progress == {"epochs_completed":1,"row_cursor":0,"optimizer_steps":3}
        and binding["record_count"] == 3 and spec.batch_size == 1 and spec.seed == 1729,
        "TRAIN-resume profile requires original three-row TRAIN3, batch1 and historical seed1729")
    population, _ = _reviewed_epoch_document(contract["old_training_binding_artifact"],limit=4*1024**2)
    _reviewed_epoch_need(population == binding,
        "TRAIN-resume exact original same-T3 data/context binding differs")
    old_config, old_config_raw = _reviewed_epoch_document(asdict(old_configuration_artifact), limit=4*1024**2)
    current_config, current_config_raw = _reviewed_epoch_document(asdict(current_configuration_artifact), limit=4*1024**2)
    old_pipeline_raw = _reviewed_decoder_artifact(old_tokenizer_pipeline_artifact,
        limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _, token_contract, token_binding = _reviewed_epoch_pipeline(old_pipeline_raw)
    _reviewed_epoch_need(contract["old_configuration_sha256"] == _digest(old_config_raw)
        and contract["current_configuration_sha256"] == _digest(current_config_raw)
        and contract["old_tokenizer_pipeline_sha256"] == _digest(old_pipeline_raw),
        "configuration or actual old pipeline capture differs")
    sources = _reviewed_train_resume_epoch_sources(contract, old, spec)
    _reviewed_epoch_need(old_config.get("device") == current_config.get("device") == "cpu"
        and old_config.get("tokenizer") == token_contract and old_config.get("tokenizer_binding") == token_binding
        and old["backend_identity"] == _reviewed_epoch_backend_identity(old_config, contract["old_source_sha256"]["worker"])
        and _thaw(spec.backend_identity) == _reviewed_epoch_backend_identity(current_config, contract["current_source_sha256"]["worker"]),
        "old and current complete configurations/identities are not authenticated")
    _reviewed_epoch_need(old["token_budgets"] == {"max_source_tokens": spec.max_source_tokens,
        "max_target_tokens": spec.max_target_tokens, "tokenizer_contract": token_contract}
        and binding.get("tokenizer_contract") == token_contract,
        "old complete tokenizer contract or budgets differ")
    _reviewed_epoch_need(set(old_config) == set(current_config)
        and all(_json_bytes(old_config[key]) == _json_bytes(current_config[key])
                for key in old_config if key not in {"tokenizer", "tokenizer_binding"}),
        "architecture/parameter/buffer/dependency versions/optimizer settings changed")
    _reviewed_epoch_need(old_config.get("model_profile") == current_config.get("model_profile") == "builtin-qwen2-bfloat16/v1"
        and old_config.get("model_class") == current_config.get("model_class") == "transformers.models.qwen2.modeling_qwen2.Qwen2ForCausalLM"
        and old_config.get("architecture") == current_config.get("architecture") == "causal_lm",
        "TRAIN-resume requires the unchanged CPU BF16 Qwen numerical profile")
    version_key = _digest(_json_bytes({"old_origin":spec.parent_checkpoint_artifact.sha256,
        "current_source":contract["current_source_sha256"],
        "population":contract["old_training_binding_artifact"]["sha256"],
        "profile":REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE}))
    lineage, version = "train-source-epoch:"+version_key, "train-source-version:"+version_key
    _reviewed_epoch_need(lineage != old["checkpoint_lineage_id"] and version != old["base_version_id"],
        "new TRAIN-resume lineage/version required; original IDs cannot be retagged")
    return {"profile":REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE,"origin_kind":"trained3",
        "new_checkpoint_lineage_id":lineage,"new_base_version_id":version,
        "old_population_binding":population,"spec": spec, "old_manifest": old, "old_manifest_raw": old_raw,
        "old_configuration": old_config, "current_configuration": current_config,
        "old_pipeline_raw": old_pipeline_raw, "contract": contract, "sources": sources,
        "old_configuration_artifact": asdict(old_configuration_artifact),
        "old_pipeline_artifact": asdict(old_tokenizer_pipeline_artifact),
        "current_configuration_artifact": asdict(current_configuration_artifact),
        "source_contract_artifact": contract_ref}

def _reviewed_train_resume_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current):
    """Existing paired transfer with exact equality, new proof, no numeric updates."""
    return _reviewed_epoch_family_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current, _family=REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE)

def _reviewed_train_resume_epoch_validate_receipt(reference, backend, *, expected_spec=None):
    """Recompute every proof and actual old/current pair; no receipt-only waiver."""
    return _reviewed_epoch_family_validate_receipt(reference, backend, expected_spec=expected_spec, _family=REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE)

def migrate_local_reviewed_decoder_train_resume_source_epoch_v5(spec, *, registry, current_admission_provider, execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact, tokenizer_artifact, license_artifact, old_configuration_artifact, old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact, output_directory, max_model_bytes, runtime_profile='builtin-qwen2-bfloat16/v1'):
    """Migrate the exact original9d TRAIN3 pair to a NEW current train-resume version.

    Actual old pipeline and current dependency-cohort snapshots must be captured
    BEFORE Source adoption. No fresh vendor import, fitting, counter/RNG reset,
    old-artifact rewrite, promotion or historical dependency requalification.
    The caller retains existing execution/resource/asset/admission ownership.
    """
    return _migrate_local_reviewed_decoder_epoch_family(spec, registry=registry, current_admission_provider=current_admission_provider, execution_guard=execution_guard, asset_policy_guard=asset_policy_guard, recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact, tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact, old_configuration_artifact=old_configuration_artifact, old_tokenizer_pipeline_artifact=old_tokenizer_pipeline_artifact, current_configuration_artifact=current_configuration_artifact, compatibility_contract_artifact=compatibility_contract_artifact, output_directory=output_directory, max_model_bytes=max_model_bytes, runtime_profile=runtime_profile, _family=REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE)

__all__ += ['migrate_local_reviewed_decoder_train_resume_source_epoch_v5', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_CONTRACT_SCHEMA', 'REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA']


def make_reviewed_decoder_digest_omitted_source_producer_v1(runtime, *, binding, rows, split_manifest,
        exposure_records, source_contexts, expected_source_contexts_sha256,
        expected_admission_inputs_sha256, backend_identity, assets, model_checkpoint,
        optimizer_checkpoint, max_source_tokens, max_output_tokens,
        allow_heldout_evaluation=False, context_profile=None,
        current_context_inputs_provider=None, expected_context_inputs_sha256=None,
        context_policy_guard=None, context_transport="plain_json_v1", generation_policy=None):
    """Bind admission V3 source or explicitly reviewed heldout TRAIN context."""
    return _make_reviewed_decoder_source_producer(runtime, binding=binding, rows=rows,
        split_manifest=split_manifest, exposure_records=exposure_records, source_contexts=source_contexts,
        expected_source_contexts_sha256=expected_source_contexts_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256,
        backend_identity=backend_identity, assets=assets, model_checkpoint=model_checkpoint,
        optimizer_checkpoint=optimizer_checkpoint, max_source_tokens=max_source_tokens,
        max_output_tokens=max_output_tokens, allow_heldout_evaluation=allow_heldout_evaluation,
        context_profile=context_profile, current_context_inputs_provider=current_context_inputs_provider,
        expected_context_inputs_sha256=expected_context_inputs_sha256,
        context_policy_guard=context_policy_guard, context_transport=context_transport, generation_policy=generation_policy, _admission_version="v3", _target_codec=REVIEWED_DIGEST_OMITTED_TARGET_CODEC)


def load_local_reviewed_decoder_digest_omitted_runtime_v1(*, admission_profile, registry, current_admission_provider,
        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,
        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,
        expected_backend_identity, expected_source_sha256,
        expected_admission_inputs_sha256, max_model_bytes,
        runtime_profile="builtin-t5-gpt2-float32/v1", cache_source_epoch_migration=None):
    """Load a local decoder only for the explicitly selected admission V3 domain."""
    if type(admission_profile) is not str or admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:
        raise TrainingJobValidationError("explicit mixed-sort admission V3 load profile required")
    return _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider,
        execution_guard=execution_guard, asset_policy_guard=asset_policy_guard,
        recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact,
        tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact,
        model_checkpoint=model_checkpoint, optimizer_checkpoint=optimizer_checkpoint,
        expected_backend_identity=expected_backend_identity, expected_source_sha256=expected_source_sha256,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256, max_model_bytes=max_model_bytes,
        _admission_version="v3", _runtime_profile=runtime_profile, _target_codec=REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
        _cache_epoch_migration_artifact=cache_source_epoch_migration)

__all__ += ["ReviewedDigestOmittedDecoderTrainingJobSpec", "REVIEWED_DIGEST_OMITTED_JOB_SCHEMA", "REVIEWED_DIGEST_OMITTED_WORKER_RECEIPT_SCHEMA", "REVIEWED_DIGEST_OMITTED_TARGET_CODEC", "REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA", "REVIEWED_DIGEST_OMITTED_CHATML_PROFILE", "REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA", "REVIEWED_DIGEST_OMITTED_RECIPE_SCHEMA", "load_local_reviewed_decoder_digest_omitted_runtime_v1", "make_reviewed_decoder_digest_omitted_source_producer_v1"]

# Closed terminal source proof glue, version 1.
_REVIEWED_DIGEST_CACHE_TERMINAL_GLUE_SHA256 = '0817f0b1455e3219df66e55ec3ae8cdc35cf4c72413408ce1a988229b8d90625'
_REVIEWED_DIGEST_CACHE_TERMINAL_REVERSE_EDITS = ((657, 659, 'e94383d6690ebf6548066989f8e62b468a58766068a5c6e972e4c68d45386c6e', ''), (3873, 3874, '4fbaa579257e2d1381c3e6b92331ee82686347fc3e1f156051f530f01a05a381', '                       max_generation_seconds=None, context_budget_profile=None):\n'), (3902, 3908, '833b25981a132ee43d6402de465a5598af5fbbdfbb0819e5d1c9ebc384dd08ec', ''), (3914, 3918, '8cb362d016fba265be23d59c889f33e159d5da3b9fc7f838d58e6e2f7980a160', ''), (4217, 4232, '3aa1cecd578198a02118661cd0741f52b1b8122e43f3dfea76dd444a6d3e3961', '                        token = int(logits[0, -1].argmax().item())\n'), (4275, 4295, '8d151c135c4aa1807f8a6eaabcecba03dc369d7602b275bf7b05cf1466f3cb91', ''), (4297, 4307, '58089cb5c137cdf4f0fb986493f0dd67e2eecc19a40e78d0a84606ec737ee10e', ''), (4415, 4416, '64b1066850c107a888c2a91e90bc7007048454c59d48a03943b50c7557c838f0', '    need((generation_copy is not None and generation_copy["schema"] == REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA) == digest_omitted,\n'), (4417, 4418, '45519e905796276255b041fefeb6637b24f0162b22bf6622fe12eaae3951c4d0', '    qwen2_generation = generation_copy is not None and generation_copy["schema"] in {"reviewed-decoder-generation-policy/v2", REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA}\n'), (4578, 4581, '9445b3fed9660fdf34ad4e387d3edf57d0d814667d0c6bbd25118556ec994ab5', '        policy.update(schema="reviewed-decoder-digest-omitted-source-producer-policy/v1",\n'), (4860, 4863, '64c9c0ce7e67e976b659f52225778a4f1ee078585d49e67f84b526eaf93dc003', '        input_profile_id=("reviewed-decoder-digest-omitted-producer/v1:" if digest_omitted else "reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2_generation\n'), (4917, 4919, '3327b1aeaf40c2cbc114ed4edf41a66be7733efac3bd1ee0bd07ceb6121140db', ''))
_REVIEWED_DIGEST_CACHE_TERMINAL_DISPATCH = "    if (b'\\nREVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA = ' in current_worker\n            or b'\\n# Closed terminal source proof glue, version 1.\\n' in current_worker):\n        return _reviewed_digest_cache_terminal_projection(old_worker,current_worker,old_inputs,current_inputs)\n"


def _reviewed_digest_cache_terminal_source_inverse(current_worker):
    """Recover complete pinned prior bytes; this is content proof, not permission."""
    need = _reviewed_epoch_need
    need(type(current_worker) is bytes, 'exact terminal source bytes required')
    prior_sha = '348fe95f15ee03d8039c1171b30d228400416f3a6fa40462f64592139ba54963'
    if len(current_worker) == 586659 and _digest(current_worker) == prior_sha:
        return current_worker
    begin = b'\n# Closed terminal source proof glue, version 1.\n'
    end = b'\n# End closed terminal source proof glue, version 1.\n'
    if begin in current_worker or end in current_worker:
        need(current_worker.count(begin) == 1 and current_worker.count(end) == 1,
            'unique complete terminal source glue required')
        lo = current_worker.index(begin)
        hi = current_worker.index(end) + len(end)
        need(hi > lo, 'terminal source glue boundaries differ')
        block = current_worker[lo:hi]
        assignment = b"\n_REVIEWED_DIGEST_CACHE_TERMINAL_GLUE_SHA256 = '"
        need(block.count(assignment) == 1, 'terminal source glue commitment missing')
        value_at = block.index(assignment) + len(assignment)
        need(block[value_at:value_at + 64] == _REVIEWED_DIGEST_CACHE_TERMINAL_GLUE_SHA256.encode()
            and block[value_at + 64:value_at + 66] == b"'\n",
            'terminal source glue commitment differs')
        normalized = block[:value_at] + b'0' * 64 + block[value_at + 64:]
        need(_digest(normalized) == _REVIEWED_DIGEST_CACHE_TERMINAL_GLUE_SHA256,
            'complete terminal source glue changed')
        current_worker = current_worker[:lo] + current_worker[hi:]
        dispatch = _REVIEWED_DIGEST_CACHE_TERMINAL_DISPATCH.encode()
        need(current_worker.count(dispatch) == 1, 'unique terminal source dispatch required')
        current_worker = current_worker.replace(dispatch, b'', 1)
    need(len(current_worker) == 591227
        and _digest(current_worker) == '6dc99f98868d69ce92c8a6218458bc9ee60d35faefc362ad42aaa8f69875a439',
        'unsupported complete terminal source target')
    lines = current_worker.decode().splitlines(keepends=True)
    for lo,hi,expected,replacement in reversed(_REVIEWED_DIGEST_CACHE_TERMINAL_REVERSE_EDITS):
        need(_digest(''.join(lines[lo:hi]).encode()) == expected,
            'exact terminal source reversal slice differs')
        lines[lo:hi] = [replacement]
    recovered = ''.join(lines).encode()
    need(len(recovered) == 586659 and _digest(recovered) == prior_sha,
        'complete prior cache source recovery differs')
    return recovered


def _reviewed_digest_cache_terminal_projection(old_worker,current_worker,old_inputs,current_inputs):
    """Compose a closed terminal inverse with the unchanged historical Source proof."""
    prior = _reviewed_digest_cache_terminal_source_inverse(current_worker)
    historical = _reviewed_digest_cache_epoch_projection(old_worker,prior,old_inputs,current_inputs)
    return {
        'schema':'reviewed-digest-cache-closed-terminal-source-projection/v1',
        'old_worker_sha256':_digest(old_worker),
        'current_worker_sha256':_digest(current_worker),
        'old_inputs_sha256':_digest(old_inputs),
        'current_inputs_sha256':_digest(current_inputs),
        'recovered_complete_prior_worker_sha256':_digest(prior),
        'terminal_source_worker_sha256':'6dc99f98868d69ce92c8a6218458bc9ee60d35faefc362ad42aaa8f69875a439',
        'closed_terminal_glue_sha256':_REVIEWED_DIGEST_CACHE_TERMINAL_GLUE_SHA256,
        'historical_source_projection':historical,
        'historical_source_projection_sha256':_digest(_json_bytes(historical)),
        'terminal_generation_code_changed':True,
        'historical_execution_requalified':False,
        'marked_parent_continuation_enabled':False,
    }

# End closed terminal source proof glue, version 1.

# Explicit same-objective digest cache Source migration, version 1.
# PRIVATE AUTHORING FRAGMENT. Copied into the existing worker, never a new module.
REVIEWED_DIGEST_CACHE_EPOCH_PROFILE = 'digest-omitted-TRAIN3-to-pure-tokenizer-caches/v1'
REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE = 'digest-omitted-PRISTINE0-to-pure-tokenizer-caches/v1'
REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA = 'reviewed-digest-omitted-cache-source-compatibility/v2'
REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SNAPSHOT_SCHEMA = 'reviewed-decoder-migration-dependency-snapshot/v2'
REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE = 'declared-current-at-migration-cohort-not-historical-execution-attestation/v1'
REVIEWED_DIGEST_CACHE_EPOCH_CONTRACT_SCHEMA = 'reviewed-digest-omitted-cache-source-compatibility/v1'
REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA = 'reviewed-digest-omitted-cache-source-migration/v1'
REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA = 'reviewed-digest-omitted-cache-source-checkpoint/v1'
_REVIEWED_DIGEST_CACHE_EPOCH_BRIDGE_AST_SHA256 = '314e74be4c92fe2dcfd511345b2dc13b950c30571b2ae258d561c2aa8fd736a5'
_REVIEWED_DIGEST_CACHE_EPOCH_REVERSE_EDITS = (('        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DIGEST_OMITTED_JOB_SCHEMA:', '        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA:\n            return ReviewedDigestCacheEpochTrainingJobSpec.from_dict(value)\n        if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_DIGEST_OMITTED_JOB_SCHEMA:', 1), ('        expected_schema = (REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if type(self) is ReviewedDigestOmittedDecoderTrainingJobSpec else', '        expected_schema = (REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA if type(self) is ReviewedDigestCacheEpochTrainingJobSpec else\n            REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if type(self) is ReviewedDigestOmittedDecoderTrainingJobSpec else', 1), ('REVIEWED_DIGEST_OMITTED_TARGET_CODEC if type(self) is ReviewedDigestOmittedDecoderTrainingJobSpec else', 'REVIEWED_DIGEST_OMITTED_TARGET_CODEC if type(self) in (ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec) else', 1), ('        expected_schema = (REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if cls is ReviewedDigestOmittedDecoderTrainingJobSpec else', '        expected_schema = (REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA if cls is ReviewedDigestCacheEpochTrainingJobSpec else\n            REVIEWED_DIGEST_OMITTED_JOB_SCHEMA if cls is ReviewedDigestOmittedDecoderTrainingJobSpec else', 1), ('        if cls in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec) and data.get("admission_profile")', '        if cls in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec) and data.get("admission_profile")', 1), ('    digest_omitted = type(spec) is ReviewedDigestOmittedDecoderTrainingJobSpec', '    digest_omitted = type(spec) in (ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec)', 1), ('    mixed = type(spec) in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec)', '    mixed = type(spec) in (ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec)', 1), ('(ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec)', '(ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec, ReviewedDigestOmittedDecoderTrainingJobSpec, ReviewedDigestCacheEpochTrainingJobSpec)', 3), ('        parent = _parse_json(parent_raw)\n        if continuation_enabled:', '        parent = _parse_json(parent_raw)\n        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:\n            parent = _reviewed_digest_cache_epoch_ancestry(spec, runtime.backend, parent, data["receipt"])\n            frozen_cache_parent = _json_bytes(parent)\n            def replay_cache_epoch(binding):\n                observed = _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)\n                if observed != parent_raw:\n                    raise TrainingJobValidationError("digest cache ancestry parent changed")\n                normalized = _reviewed_digest_cache_epoch_ancestry(spec, runtime.backend, _parse_json(observed), binding)\n                if _json_bytes(normalized) != frozen_cache_parent:\n                    raise TrainingJobValidationError("digest cache ancestry changed during execution")\n            continuation_replay = replay_cache_epoch\n        if continuation_enabled:', 1), ('        current()\n        checkpoint_ref = _write_exclusive(output / "reviewed-decoder-checkpoint.json", _json_bytes(checkpoint))', '        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:\n            checkpoint.update(schema=REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA,\n                cache_source_epoch_migration=asdict(spec.cache_source_epoch_migration),\n                cache_epoch_parent_checkpoint_artifact=asdict(spec.parent_checkpoint_artifact))\n        current()\n        checkpoint_ref = _write_exclusive(output / "reviewed-decoder-checkpoint.json", _json_bytes(checkpoint))', 1), ('        if mixed:\n            receipt["admission_profile"] = admission_profile', '        if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec:\n            receipt.update(cache_source_epoch_migration=asdict(spec.cache_source_epoch_migration),\n                checkpoint_schema=REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA,\n                cache_source_epoch_profile=_thaw(runtime.backend.cache_source_epoch_marker)["profile"])\n        if mixed:\n            receipt["admission_profile"] = admission_profile', 1), ('    if digest_omitted and (_admission_version != "v3" or _source_epoch_migration is not None):\n        raise TrainingJobValidationError("digest-omitted loader requires fresh current-source admission; no old-objective migration")', '    if digest_omitted and (_admission_version != "v3" or (_source_epoch_migration is not None and\n            (type(_source_epoch_migration) is not dict or _source_epoch_migration.get("profile") not in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE)))):\n        raise TrainingJobValidationError("digest-omitted loader requires fresh current-source admission; no old-objective migration")\n    if digest_omitted and _source_epoch_migration is not None:\n        _reviewed_digest_cache_epoch_loader_context(_source_epoch_migration, model_checkpoint,\n            optimizer_checkpoint, expected_backend_identity, expected_source_sha256, expected_admission_inputs_sha256)', 1), ('    if llama_profile:\n        policy["runtime_profile"] = _runtime_profile', '    if digest_omitted and _source_epoch_migration is not None:\n        policy["source_epoch_migration_profile"] = _source_epoch_migration["profile"]\n    if llama_profile:\n        policy["runtime_profile"] = _runtime_profile', 1), ('        if _source_epoch_migration is not None:\n            model_raw, optimizer_raw = _reviewed_epoch_restore(backend, model_raw, optimizer_raw,\n                _source_epoch_migration, registry, current_admission_provider, current)', '        if digest_omitted and _source_epoch_migration is not None:\n            model_raw, optimizer_raw = _reviewed_digest_cache_epoch_restore(backend, model_raw, optimizer_raw,\n                _source_epoch_migration, registry, current_admission_provider, current)\n        elif _source_epoch_migration is not None:\n            model_raw, optimizer_raw = _reviewed_epoch_restore(backend, model_raw, optimizer_raw,\n                _source_epoch_migration, registry, current_admission_provider, current)', 1), ('training_conditioning_profile=None, target_codec="complete-reviewed-norm-json/v2"):', 'training_conditioning_profile=None, target_codec="complete-reviewed-norm-json/v2", cache_source_epoch_marker=None):', 1), ('        self.target_codec = target_codec\n        self.training_conditioning_profile =', '        if cache_source_epoch_marker is not None:\n            if target_codec != REVIEWED_DIGEST_OMITTED_TARGET_CODEC or model_profile != "builtin-qwen2-bfloat16/v1" or architecture != "causal_lm":\n                raise TrainingJobValidationError("cache marker requires the explicit same-digest Qwen profile")\n            cache_source_epoch_marker = _reviewed_digest_cache_epoch_validate_marker(cache_source_epoch_marker)\n        self.cache_source_epoch_marker = (_freeze(cache_source_epoch_marker) if cache_source_epoch_marker is not None else None)\n        self.target_codec = target_codec\n        self.training_conditioning_profile =', 1), ('        rotary = dict(self.model.named_modules()).get("model.rotary_emb")', '        if self.cache_source_epoch_marker is not None:\n            configuration["cache_source_epoch_marker"] = _thaw(self.cache_source_epoch_marker)\n        rotary = dict(self.model.named_modules()).get("model.rotary_emb")', 1), ('    prepared = None\n    continuation_replay = None', '    if type(spec) is ReviewedDigestCacheEpochTrainingJobSpec or (type(runtime.backend) is TorchReviewedDecoderBackend and runtime.backend.cache_source_epoch_marker is not None):\n        _reviewed_digest_cache_epoch_require_job(spec, runtime.backend)\n    prepared = None\n    continuation_replay = None', 1), ('        _source_epoch_migration=None, _target_codec="complete-reviewed-norm-json/v2"):', '        _source_epoch_migration=None, _target_codec="complete-reviewed-norm-json/v2", _cache_epoch_migration_artifact=None):', 1), ('    if type(_runtime_profile) is not str or _runtime_profile not in {', '    cache_epoch_marker = None\n    if _cache_epoch_migration_artifact is not None:\n        if not digest_omitted or _source_epoch_migration is not None:\n            raise TrainingJobValidationError("cache receipt is exclusive to marked same-digest reload")\n        cache_epoch_marker = _reviewed_digest_cache_epoch_load_receipt(_cache_epoch_migration_artifact,\n            expected_backend_identity, expected_source_sha256, expected_admission_inputs_sha256)\n    elif digest_omitted and _source_epoch_migration is not None:\n        cache_epoch_marker = _source_epoch_migration["current_configuration"]["cache_source_epoch_marker"]\n    if type(_runtime_profile) is not str or _runtime_profile not in {', 1), ('            **({"target_codec": _target_codec} if digest_omitted else {}))', '            **({"target_codec": _target_codec} if digest_omitted else {}),\n            **({"cache_source_epoch_marker": cache_epoch_marker} if cache_epoch_marker is not None else {}))', 1), ('        if backend.identity() != identity or not backend.restored_checkpoint_matches(model_raw, optimizer_raw):', '        if _cache_epoch_migration_artifact is not None:\n            _reviewed_digest_cache_epoch_validate_receipt(asdict(_cache_epoch_migration_artifact), backend, expected_spec=None)\n            receipt["cache_source_epoch_migration"] = asdict(_cache_epoch_migration_artifact)\n            receipt["cache_source_epoch_marker"] = _thaw(backend.cache_source_epoch_marker)\n            current()\n        if backend.identity() != identity or not backend.restored_checkpoint_matches(model_raw, optimizer_raw):', 1), ('def load_local_reviewed_decoder_digest_omitted_runtime_v1(*, admission_profile, registry, current_admission_provider,\n        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,\n        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,\n        expected_backend_identity, expected_source_sha256,\n        expected_admission_inputs_sha256, max_model_bytes,\n        runtime_profile="builtin-t5-gpt2-float32/v1"):\n    """Load a local decoder only for the explicitly selected admission V3 domain."""\n    if type(admission_profile) is not str or admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:\n        raise TrainingJobValidationError("explicit mixed-sort admission V3 load profile required")\n    return _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider,\n        execution_guard=execution_guard, asset_policy_guard=asset_policy_guard,\n        recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact,\n        tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact,\n        model_checkpoint=model_checkpoint, optimizer_checkpoint=optimizer_checkpoint,\n        expected_backend_identity=expected_backend_identity, expected_source_sha256=expected_source_sha256,\n        expected_admission_inputs_sha256=expected_admission_inputs_sha256, max_model_bytes=max_model_bytes,\n        _admission_version="v3", _runtime_profile=runtime_profile, _target_codec=REVIEWED_DIGEST_OMITTED_TARGET_CODEC)', 'def load_local_reviewed_decoder_digest_omitted_runtime_v1(*, admission_profile, registry, current_admission_provider,\n        execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact,\n        tokenizer_artifact, license_artifact, model_checkpoint, optimizer_checkpoint,\n        expected_backend_identity, expected_source_sha256,\n        expected_admission_inputs_sha256, max_model_bytes,\n        runtime_profile="builtin-t5-gpt2-float32/v1", cache_source_epoch_migration=None):\n    """Load a local decoder only for the explicitly selected admission V3 domain."""\n    if type(admission_profile) is not str or admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:\n        raise TrainingJobValidationError("explicit mixed-sort admission V3 load profile required")\n    return _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider,\n        execution_guard=execution_guard, asset_policy_guard=asset_policy_guard,\n        recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact,\n        tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact,\n        model_checkpoint=model_checkpoint, optimizer_checkpoint=optimizer_checkpoint,\n        expected_backend_identity=expected_backend_identity, expected_source_sha256=expected_source_sha256,\n        expected_admission_inputs_sha256=expected_admission_inputs_sha256, max_model_bytes=max_model_bytes,\n        _admission_version="v3", _runtime_profile=runtime_profile, _target_codec=REVIEWED_DIGEST_OMITTED_TARGET_CODEC,\n        _cache_epoch_migration_artifact=cache_source_epoch_migration)', 1), ('def _reviewed_epoch_dependencies(reference, old_manifest, old_config_sha, old_pipeline_sha, backend):', 'def _reviewed_epoch_dependencies(reference, old_manifest, old_config_sha, old_pipeline_sha, backend, *, _current_cache_contract=None):', 1), ('    fields = {"schema", "association_scope", "old_checkpoint_manifest_sha256", "old_configuration_sha256",\n              "old_tokenizer_pipeline_sha256", "old_source_sha256", "implementation"}\n    _reviewed_epoch_need(type(snapshot) is dict and set(snapshot) == fields\n        and snapshot["schema"] == "reviewed-decoder-migration-dependency-snapshot/v1"\n        and snapshot["association_scope"] == "declared-current-cohort-before-Source-transition-not-historical-execution-attestation/v1"\n        and snapshot["old_checkpoint_manifest_sha256"] == old_manifest["artifact_sha256"]\n        and snapshot["old_configuration_sha256"] == old_config_sha\n        and snapshot["old_tokenizer_pipeline_sha256"] == old_pipeline_sha\n        and snapshot["old_source_sha256"] == old_manifest["producer_pins"],\n        "frozen dependency snapshot does not bind the actual old pair/configuration")\n', '    if _current_cache_contract is None:\n        fields = {"schema", "association_scope", "old_checkpoint_manifest_sha256", "old_configuration_sha256",\n                  "old_tokenizer_pipeline_sha256", "old_source_sha256", "implementation"}\n        _reviewed_epoch_need(type(snapshot) is dict and set(snapshot) == fields\n            and snapshot["schema"] == "reviewed-decoder-migration-dependency-snapshot/v1"\n            and snapshot["association_scope"] == "declared-current-cohort-before-Source-transition-not-historical-execution-attestation/v1"\n            and snapshot["old_checkpoint_manifest_sha256"] == old_manifest["artifact_sha256"]\n            and snapshot["old_configuration_sha256"] == old_config_sha\n            and snapshot["old_tokenizer_pipeline_sha256"] == old_pipeline_sha\n            and snapshot["old_source_sha256"] == old_manifest["producer_pins"],\n            "frozen dependency snapshot does not bind the actual old pair/configuration")\n    else:\n        _reviewed_digest_cache_current_dependency_metadata(snapshot,old_manifest,old_config_sha,old_pipeline_sha,_current_cache_contract)\n', 1))
_REVIEWED_DIGEST_CACHE_EPOCH_FAMILY_WRAPPERS = {'_reviewed_train_resume_epoch_restore': {'wrapper_AST_sha256': '4184d7296b1d57958d9c196575007ae9de3d64a3772fbcff951982a51894f056', 'old_AST_sha256': 'c3822e312a729015dd52e2712042e4834f5590354aecce6f0e21541b539a4914', 'old_raw_sha256': 'ed6aaa9b9c27bb09b53aaf00fa7bad7bec648cecb97e068565dcda301efccaff'}, '_reviewed_train_resume_epoch_validate_receipt': {'wrapper_AST_sha256': '209b39d954ac4da77d7f9a6095ff1ec42932d3fd6b2c9506c26ba3a475d4735f', 'old_AST_sha256': 'cbf826d91418031fe8f763b1946712346dded2e949f7efc78e9ad9e2b810cb13', 'old_raw_sha256': 'f198819931ab9f59d8186113d2f751f321c2fa95f32944b3dc29752f69711d8e'}, 'migrate_local_reviewed_decoder_train_resume_source_epoch_v5': {'wrapper_AST_sha256': 'c491f2fca9ee8579d965cd044da07872792bd9254f4c637f423a024d31ed671c', 'old_AST_sha256': 'dd39e27dfa3123363f1bb384ce64f36a7ca7b2edbb0dd7019e81037c153bbfae', 'old_raw_sha256': '2923f53b21466057bfbf78ce6b04d7d01a570933dcc68bf3e4ccaed11953fd7c'}}
_REVIEWED_DIGEST_CACHE_EPOCH_CACHE_AST = {'worker': {'added': {'_reviewed_tokenizer_binding_derivation': '8792ee9a94604328211e8233aa7f5cd0e045b04ecb1dabd3c8ba6b7acd1bf75a'}, 'old_changed': 'd1596ff3ff39056eeb90498e55a9e2e2d1da84b97fa66e7eca95f9c5c2f03e50', 'new_changed': 'a8e7a73d60c9d82ef8fee669dc6b4a36f29e5bb0db61128381fb8783ffe57ff1', 'added_statements': ["Assign(targets=[Name(id='_REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_RAW_BYTES', ctx=Store())], value=BinOp(left=BinOp(left=Constant(value=16), op=Mult(), right=Constant(value=1024)), op=Mult(), right=Constant(value=1024)))", "Assign(targets=[Name(id='_REVIEWED_TOKENIZER_BINDING_DERIVATION_MAX_ENTRIES', ctx=Store())], value=Constant(value=2))", "Assign(targets=[Name(id='_REVIEWED_TOKENIZER_BINDING_DERIVATION_CACHE', ctx=Store())], value=Dict(keys=[], values=[]))", "Assign(targets=[Name(id='_REVIEWED_TOKENIZER_BINDING_DERIVATION_LOCK', ctx=Store())], value=Call(func=Attribute(value=Name(id='threading', ctx=Load()), attr='RLock', ctx=Load()), args=[], keywords=[]))"]}, 'inputs': {'added': {'_reviewed_decoder_hf_pipeline_summary': 'a93824dc73961b626919a2739bc0534c5b1076348d9b2d887dcd8aac51c5df3f'}, 'old_changed': 'dcd5f10e84c0dbf85d06f3f6e9fa0e69332f6d1e51bf1ac166561f8ba9e434ce', 'new_changed': 'b536336addd2d8c5c6ef09b7c65ca1f67cc5c9f72b80887de7eb8764a86e68e3', 'added_statements': ["Import(names=[alias(name='threading', asname='_reviewed_decoder_pipeline_cache_threading')])", "Assign(targets=[Name(id='_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE', ctx=Store())], value=Dict(keys=[], values=[]))", "Assign(targets=[Name(id='_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_LOCK', ctx=Store())], value=Call(func=Attribute(value=Name(id='_reviewed_decoder_pipeline_cache_threading', ctx=Load()), attr='Lock', ctx=Load()), args=[], keywords=[]))", "Assign(targets=[Name(id='_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_ENTRIES', ctx=Store())], value=Constant(value=2))", "Assign(targets=[Name(id='_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_RAW_BYTES', ctx=Store())], value=BinOp(left=Constant(value=16), op=Mult(), right=BinOp(left=Constant(value=1024), op=Pow(), right=Constant(value=2))))"]}}


def _reviewed_digest_cache_epoch_projection(old_worker, current_worker, old_inputs, current_inputs):
    """Reverse exact reviewed edits; no archived source or caller code executes."""
    import ast
    import copy
    need = _reviewed_epoch_need
    need(all(type(raw) is bytes for raw in (old_worker,current_worker,old_inputs,current_inputs)),
        'exact source bytes required')
    need(_digest(old_worker)=='65d55a34f097a4b673464ef59b87942274e65eb5083ea79d01759f8df16372f2'
        and _digest(old_inputs)=='7fbcfeb40e6f0d68537d0601169fbc208c3b6ca36273d786a85d876720323afb'
        and _digest(current_inputs)=='88125051a7b1d0dcc887f772faa750fa13b8a2141693679a62e2bd5e97e92db3',
        'unsupported cache source origin/input target')
    if (b'\nREVIEWED_DIGEST_OMITTED_TERMINAL_POLICY_SCHEMA = ' in current_worker
            or b'\n# Closed terminal source proof glue, version 1.\n' in current_worker):
        return _reviewed_digest_cache_terminal_projection(old_worker,current_worker,old_inputs,current_inputs)
    marker=b'\n# Explicit same-objective digest cache Source migration, version 1.\n'
    need(current_worker.count(marker)==1,'unique complete cache bridge required')
    prefix, bridge=current_worker.split(marker,1)
    body=ast.parse(bridge)
    assignments=[n for n in body.body if isinstance(n,ast.Assign) and len(n.targets)==1
        and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='_REVIEWED_DIGEST_CACHE_EPOCH_BRIDGE_AST_SHA256']
    need(len(assignments)==1 and isinstance(assignments[0].value,ast.Constant)
        and assignments[0].value.value==_REVIEWED_DIGEST_CACHE_EPOCH_BRIDGE_AST_SHA256,
        'closed bridge commitment differs')
    assignments[0].value=ast.Constant('0'*64)
    need(_digest(ast.dump(body,include_attributes=False).encode())==_REVIEWED_DIGEST_CACHE_EPOCH_BRIDGE_AST_SHA256,
        'complete migration bridge implementation changed')
    old_definitions={n.name:n for n in ast.parse(old_worker).body if isinstance(n,ast.FunctionDef)}
    for name,rule in _REVIEWED_DIGEST_CACHE_EPOCH_FAMILY_WRAPPERS.items():
        current_definitions={n.name:n for n in ast.parse(prefix).body if isinstance(n,ast.FunctionDef)}
        old_node,current_node=old_definitions[name],current_definitions[name]
        old_text=ast.get_source_segment(old_worker.decode(),old_node)
        current_text=ast.get_source_segment(prefix.decode(),current_node)
        need(_digest(ast.dump(old_node,include_attributes=False).encode())==rule['old_AST_sha256']
            and _digest(old_text.encode())==rule['old_raw_sha256']
            and _digest(ast.dump(current_node,include_attributes=False).encode())==rule['wrapper_AST_sha256']
            and prefix.count(current_text.encode())==1,'exact historical family wrapper changed')
        prefix=prefix.replace(current_text.encode(),old_text.encode(),1)
    for old,new,count in reversed(_REVIEWED_DIGEST_CACHE_EPOCH_REVERSE_EDITS):
        need(prefix.count(new.encode())==count,'exact migration dispatch edit changed')
        prefix=prefix.replace(new.encode(),old.encode(),count)
    need(_digest(prefix)=='93ce5efa62a999a681a8e00ce75cf87b6c697428c8b7037abbd5bb7275afe3f6',
        'migration reversal did not recover exact qualified cache worker')
    dump=lambda node:ast.dump(node,include_attributes=False)
    for role,old_raw,new_raw in (('worker',old_worker,prefix),('inputs',old_inputs,current_inputs)):
        old_tree,new_tree=ast.parse(old_raw),ast.parse(new_raw)
        rules=_REVIEWED_DIGEST_CACHE_EPOCH_CACHE_AST[role]
        def named(tree):
            result={}
            for n in tree.body:
                if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
                    need(n.name not in result,'duplicate cache source definition');result[n.name]=n
            return result
        od,nd=named(old_tree),named(new_tree)
        for name,h in rules['added'].items():
            need(name in nd and _digest(dump(nd[name]).encode())==h,'exact cache helper changed')
            new_tree.body.remove(nd[name])
        if role=='worker':
            om={n.name:n for n in od['ReviewedPretrainedTokenizer'].body if isinstance(n,ast.FunctionDef)}
            nm={n.name:n for n in nd['ReviewedPretrainedTokenizer'].body if isinstance(n,ast.FunctionDef)}
            old,new=om['binding_metadata'],nm['binding_metadata']
            need(_digest(dump(old).encode())==rules['old_changed'] and _digest(dump(new).encode())==rules['new_changed'],
                'exact binding derivation delta changed')
            index=nd['ReviewedPretrainedTokenizer'].body.index(new)
            nd['ReviewedPretrainedTokenizer'].body[index]=copy.deepcopy(old)
        else:
            old,new=od['_reviewed_decoder_tokenizer_contract'],nd['_reviewed_decoder_tokenizer_contract']
            need(_digest(dump(old).encode())==rules['old_changed'] and _digest(dump(new).encode())==rules['new_changed'],
                'exact pipeline summary delta changed')
            new_tree.body[new_tree.body.index(new)]=copy.deepcopy(old)
        for encoded in rules['added_statements']:
            found=[n for n in new_tree.body if dump(n)==encoded]
            need(len(found)==1,'exact cache global/import delta changed');new_tree.body.remove(found[0])
        need(dump(old_tree)==dump(new_tree),'unrelated source/numerical/tokenizer default changed')
    return {'schema':'reviewed-digest-cache-exact-source-projection/v1',
        'old_worker_sha256':_digest(old_worker),'cache_worker_sha256':_digest(prefix),
        'current_worker_sha256':_digest(current_worker),'old_inputs_sha256':_digest(old_inputs),
        'current_inputs_sha256':_digest(current_inputs),
        'closed_bridge_AST_sha256':_REVIEWED_DIGEST_CACHE_EPOCH_BRIDGE_AST_SHA256,
        'numerical_and_all_other_old_AST_exact':True}


def _reviewed_digest_cache_epoch_sources(contract, origin, spec, *, _profile=REVIEWED_DIGEST_CACHE_EPOCH_PROFILE):
    from ...logic.autoformal import training_cycle_inputs as inputs
    need=_reviewed_epoch_need
    need(_profile in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE),'closed digest cache origin profile required')
    fields={'schema','profile','old_checkpoint_manifest_sha256','old_configuration_sha256',
        'current_configuration_sha256','old_tokenizer_pipeline_sha256','old_source_sha256',
        'current_source_sha256','old_source_artifacts','current_source_artifacts',
        'dependency_snapshot_artifact','old_training_binding_artifact'}
    if type(contract)is dict and contract.get('schema')==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA:
        need(set(contract)==fields|{'dependency_association_scope'} and contract['profile']==_profile
            and contract['dependency_association_scope']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE,'closed explicit current-at-migration digest contract required')
    else:
        need(type(contract)is dict and set(contract)==fields
            and contract['schema']==REVIEWED_DIGEST_CACHE_EPOCH_CONTRACT_SCHEMA
            and contract['profile']==_profile,'closed same-digest cache contract required')
    old,new=contract['old_source_sha256'],contract['current_source_sha256']
    need(type(old)is type(new)is dict and set(old)==set(new)==REVIEWED_DECODER_SOURCE_NAMES
        and old==origin['producer_pins']and new==_thaw(spec.expected_source_sha256)
        and contract['old_checkpoint_manifest_sha256']==spec.parent_checkpoint_artifact.sha256
        and all(old[k]==new[k]for k in ('consumer','admission','splits'))
        and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile)==new,
        'exact old/current Source5 and unchanged common producers required')
    oldrefs,newrefs=contract['old_source_artifacts'],contract['current_source_artifacts']
    need(type(oldrefs)is type(newrefs)is dict and set(oldrefs)==set(newrefs)=={'worker','inputs'},
        'both exact physical source pairs required')
    oldraw,newraw={},{}
    for key in ('worker','inputs'):
        oldraw[key]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(oldrefs[key]),limit=2*1024**2)
        newraw[key]=_reviewed_decoder_artifact(CheckpointArtifact.from_dict(newrefs[key]),limit=2*1024**2)
        need(_digest(oldraw[key])==old[key]and _digest(newraw[key])==new[key],'source body digest differs')
    need(Path(newrefs['worker']['path'])==Path(__file__)
        and Path(newrefs['inputs']['path'])==Path(inputs.__file__),'current physical cache source origin differs')
    projection=_reviewed_digest_cache_epoch_projection(oldraw['worker'],newraw['worker'],oldraw['inputs'],newraw['inputs'])
    return {'old_worker':oldraw['worker'],'current_worker':newraw['worker'],
        'old_inputs':oldraw['inputs'],'current_inputs':newraw['inputs'],
        'projection_sha256':_digest(_json_bytes(projection)),'cache_projection':projection}


def _reviewed_digest_cache_epoch_identity(configuration, worker_sha):
    return {'backend_id':'torch-digest-omitted-reviewed-decoder/v1:'+_digest(_json_bytes(configuration)),
        'implementation_sha256':worker_sha,'checkpoint_format':'torch-weights-only-digest-omitted-reviewed-state-pair/v1',
        'target_codec':REVIEWED_DIGEST_OMITTED_TARGET_CODEC,'source_conditioned':True,
        'pretrained':configuration['pretrained_declaration']}


def _reviewed_digest_cache_epoch_prepare_binding(spec, registry, tokenizer, current_admission_provider):
    from ...logic.autoformal import training_cycle_inputs as inputs
    exposure_raw=_reviewed_decoder_artifact(spec.exposure_artifact)
    contexts_raw=_reviewed_decoder_artifact(spec.source_contexts_artifact)
    exposure,contexts=_parse_json(exposure_raw),_parse_json(contexts_raw)
    _reviewed_epoch_need(_json_bytes(exposure)==exposure_raw and _json_bytes(contexts)==contexts_raw,
        'canonical exact digest context/exposure required')
    return inputs.prepare_reviewed_mixed_decoder_digest_omitted_inputs_v1(registry,
        admission_profile=spec.admission_profile,stage_artifact=asdict(spec.stage_artifact),
        expected_stage_sha256=spec.stage_artifact.sha256,current_admission_inputs=current_admission_provider(),
        expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256,
        exposure_records=exposure,expected_exposure_sha256=spec.exposure_artifact.sha256,
        source_contexts=contexts,expected_source_contexts_sha256=spec.source_contexts_artifact.sha256,
        split_config=_thaw(spec.split_config),expected_split_config_sha256=spec.expected_split_config_sha256,
        tokenizer=tokenizer,max_source_tokens=spec.max_source_tokens,max_target_tokens=spec.max_target_tokens,
        allow_fictional_fixture=spec.allow_fictional_fixture)


def _reviewed_digest_cache_epoch_binding_proof(old, current, contract):
    need=_reviewed_epoch_need
    need(type(old)is type(current)is dict and set(old)==set(current)
        and old.get('schema')==current.get('schema')=='reviewed-decoder-digest-omitted-training-input-receipt/v1'
        and old.get('target_codec')==current.get('target_codec')==REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
        'complete same-objective digest receipt fields required')
    for key in set(old)-{'implementation','tokenizer_contract'}:
        need(_json_bytes(old[key])==_json_bytes(current[key]),'digest population/context/token/admission drift: '+key)
    old_impl,new_impl=dict(old['implementation']),dict(current['implementation'])
    oldkeys=[k for k,v in old_impl.items()if v==contract['old_source_sha256']['inputs']]
    newkeys=[k for k,v in new_impl.items()if v==contract['current_source_sha256']['inputs']]
    need(len(oldkeys)==len(newkeys)==1,'unique exact input implementation binding required')
    old_impl.pop(oldkeys[0]);new_impl.pop(newkeys[0])
    need(old_impl==new_impl,'unrelated input dependency changed')


def _reviewed_digest_cache_epoch_context(spec, old_configuration_artifact, old_tokenizer_pipeline_artifact,
        current_configuration_artifact, compatibility_contract_artifact, *, _origin_kind='trained3'):
    need=_reviewed_epoch_need
    need(_origin_kind in ('trained3','pristine0'),'closed digest cache origin required')
    profile=REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE if _origin_kind=='pristine0' else REVIEWED_DIGEST_CACHE_EPOCH_PROFILE
    need(type(spec)is ReviewedDigestOmittedDecoderTrainingJobSpec and spec.continuation_profile is None
        and getattr(spec,'cache_source_epoch_migration',None)is None,'explicit unmigrated same-digest job required')
    contract_ref=asdict(compatibility_contract_artifact)
    contract,_=_reviewed_epoch_document(contract_ref,limit=2*1024**2)
    old,old_raw=_reviewed_epoch_document(asdict(spec.parent_checkpoint_artifact),limit=4*1024**2)
    common={'schema','checkpoint_lineage_id','base_version_id','backend_identity','assets','training_binding',
        'model_state','optimizer_state','progress','batch_size','seed','parent_checkpoint_sha256',
        'producer_pins','token_budgets','qualified','promotion_performed'}
    need(type(old)is dict and set(old)==common and old['schema']==REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA
        and old['qualified']is False and old['promotion_performed']is False,'original unmigrated digest checkpoint required')
    need(old['model_state']==asdict(spec.base_model_checkpoint)and old['optimizer_state']==asdict(spec.base_optimizer_checkpoint)
        and old['checkpoint_lineage_id']==spec.checkpoint_lineage_id and old['base_version_id']==spec.base_version_id
        and old['assets']==[asdict(x)for x in(spec.model_artifact,spec.tokenizer_artifact,spec.license_artifact,*spec.backend_artifacts)]
        and type(old['batch_size'])is int and old['batch_size']==spec.batch_size==1
        and type(old['seed'])is int and old['seed']==spec.seed==1729,'unchanged exact pair/assets/lineage/batch/seed required')
    if _origin_kind == 'pristine0':
        population,_=_reviewed_epoch_document(contract['old_training_binding_artifact'],limit=4*1024**2)
        _reviewed_digest_cache_pristine_origin(old,population,spec.stage_artifact.sha256)
    else:
        progress=old['progress'];population=old['training_binding']
        need(type(progress)is dict and progress=={'epochs_completed':1,'row_cursor':0,'optimizer_steps':3}
            and all(type(x)is int for x in progress.values())and type(population)is dict
            and population.get('schema')=='reviewed-decoder-digest-omitted-training-input-receipt/v1'
            and population.get('target_codec')==REVIEWED_DIGEST_OMITTED_TARGET_CODEC
            and type(population.get('record_count'))is int and population['record_count']==3
            and population.get('stage_artifact_sha256')==spec.stage_artifact.sha256,
            'original same-objective completed T3/steps3 population required')
    sources=_reviewed_digest_cache_epoch_sources(contract,old,spec,_profile=profile)
    bound,_=_reviewed_epoch_document(contract['old_training_binding_artifact'],limit=4*1024**2)
    need(bound==population,'original full population/context/target projection binding differs')
    old_config,old_config_raw=_reviewed_epoch_document(asdict(old_configuration_artifact),limit=4*1024**2)
    new_config,new_config_raw=_reviewed_epoch_document(asdict(current_configuration_artifact),limit=4*1024**2)
    old_pipeline=_reviewed_decoder_artifact(old_tokenizer_pipeline_artifact,limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _,token_contract,token_binding=_reviewed_epoch_pipeline(old_pipeline)
    need(contract['old_configuration_sha256']==_digest(old_config_raw)
        and contract['current_configuration_sha256']==_digest(new_config_raw)
        and contract['old_tokenizer_pipeline_sha256']==_digest(old_pipeline),'actual complete configs/pipeline differ')
    expected_marker=_reviewed_digest_cache_epoch_marker(spec.parent_checkpoint_artifact.sha256,contract['current_source_sha256'],contract['old_training_binding_artifact']['sha256'],_profile=profile)
    need('cache_source_epoch_marker'not in old_config and new_config.get('cache_source_epoch_marker')==expected_marker
        and set(new_config)==set(old_config)|{'cache_source_epoch_marker'}and all(_json_bytes(old_config[k])==_json_bytes(new_config[k])
        for k in old_config if k not in {'tokenizer','tokenizer_binding'}),
        'numeric/recipe/profile/optimizer/dependency configuration changed')
    need(old_config.get('device')==new_config.get('device')=='cpu'
        and old_config.get('model_profile')==new_config.get('model_profile')=='builtin-qwen2-bfloat16/v1'
        and old_config.get('architecture')==new_config.get('architecture')=='causal_lm'
        and old_config.get('target_codec')==new_config.get('target_codec')==REVIEWED_DIGEST_OMITTED_TARGET_CODEC
        and old_config.get('training_conditioning_profile')==new_config.get('training_conditioning_profile')==REVIEWED_DIGEST_OMITTED_CHATML_PROFILE
        and old_config.get('tokenizer')==token_contract and old_config.get('tokenizer_binding')==token_binding
        and old['backend_identity']==_reviewed_digest_cache_epoch_identity(old_config,contract['old_source_sha256']['worker'])
        and _thaw(spec.backend_identity)==_reviewed_digest_cache_epoch_identity(new_config,contract['current_source_sha256']['worker']),
        'same digest CPU BF16 Qwen/ChatML identity and complete tokenizer contract required')
    need(old['token_budgets']=={'max_source_tokens':spec.max_source_tokens,'max_target_tokens':spec.max_target_tokens,'tokenizer_contract':token_contract}
        and population.get('tokenizer_contract')==token_contract,'same complete tokenizer budget binding required')
    version=_digest(_json_bytes({'profile':profile,
        'old_manifest':spec.parent_checkpoint_artifact.sha256,'current_source':contract['current_source_sha256'],
        'population':contract['old_training_binding_artifact']['sha256']}))
    return {'profile':profile,'origin_kind':_origin_kind,
        'new_checkpoint_lineage_id':'digest-cache-source-lineage:'+version,'new_base_version_id':'digest-cache-source-version:'+version,
        'old_population_binding':population,'spec':spec,'old_manifest':old,'old_manifest_raw':old_raw,
        'old_configuration':old_config,'current_configuration':new_config,'old_pipeline_raw':old_pipeline,
        'contract':contract,'sources':sources,'old_configuration_artifact':asdict(old_configuration_artifact),
        'old_pipeline_artifact':asdict(old_tokenizer_pipeline_artifact),
        'current_configuration_artifact':asdict(current_configuration_artifact),'source_contract_artifact':contract_ref}


def _reviewed_digest_cache_epoch_receipt_spec(receipt, old_manifest, backend):
    spec=ReviewedDigestOmittedDecoderTrainingJobSpec.from_dict(receipt['target_job_spec'])
    _reviewed_epoch_need(type(backend)is TorchReviewedDecoderBackend and backend.identity()==_thaw(spec.backend_identity),
        'receipt requires actual same-objective current backend')
    return spec


def _reviewed_digest_cache_epoch_ancestry(spec, backend, manifest, current_binding):
    """Mandatory bounded replay for root and EVERY subsequent digest resume."""
    need=_reviewed_epoch_need
    reference=getattr(spec,'cache_source_epoch_migration',None)
    need(type(reference)is CheckpointArtifact,'explicit exact cache migration receipt artifact required')
    receipt=_reviewed_digest_cache_epoch_validate_receipt(asdict(reference),backend,expected_spec=spec)
    common={'schema','checkpoint_lineage_id','base_version_id','backend_identity','assets','training_binding',
        'model_state','optimizer_state','progress','batch_size','seed','parent_checkpoint_sha256',
        'producer_pins','token_budgets','qualified','promotion_performed'}
    extra={'cache_source_epoch_migration','cache_epoch_parent_checkpoint_artifact'}
    latest=_parse_json(_json_bytes(manifest));node=latest;seen=set();observed=[];later=None
    for depth in range(128):
        need(type(node)is dict and set(node)==common|extra
            and node['schema']==REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA
            and node['cache_source_epoch_migration']==asdict(reference)
            and node['checkpoint_lineage_id']==spec.checkpoint_lineage_id==receipt['new_checkpoint_lineage_id']
            and node['base_version_id']==spec.base_version_id==receipt['new_base_version_id']
            and node['backend_identity']==_thaw(spec.backend_identity)
            and node['producer_pins']==_thaw(spec.expected_source_sha256)
            and node['training_binding']==current_binding==receipt['migrated_training_binding']
            and node['assets']==[asdict(x)for x in(spec.model_artifact,spec.tokenizer_artifact,spec.license_artifact,*spec.backend_artifacts)]
            and node['token_budgets']=={'max_source_tokens':spec.max_source_tokens,'max_target_tokens':spec.max_target_tokens,'tokenizer_contract':current_binding['tokenizer_contract']}
            and type(node['batch_size'])is int and node['batch_size']==spec.batch_size
            and type(node['seed'])is int and node['seed']==spec.seed
            and node['qualified']is False and node['promotion_performed']is False,'closed same-digest cache checkpoint ancestry differs')
        progress=node['progress']
        need(type(progress)is dict and set(progress)=={'epochs_completed','row_cursor','optimizer_steps'}
            and all(type(x)is int and 0<=x<=10**9 for x in progress.values())
            and progress['row_cursor']<3 and progress['row_cursor']%spec.batch_size==0
            and progress['optimizer_steps']==progress['epochs_completed']*math.ceil(3/spec.batch_size)+progress['row_cursor']//spec.batch_size
            and progress['optimizer_steps']>=receipt['original_progress']['optimizer_steps']
            and(later is None or later>progress['optimizer_steps']),'cache ancestry rewinds/relabels optimizer progress')
        CheckpointArtifact.from_dict(node['model_state']);CheckpointArtifact.from_dict(node['optimizer_state'])
        parent=asdict(CheckpointArtifact.from_dict(node['cache_epoch_parent_checkpoint_artifact']))
        need(parent['sha256']==node['parent_checkpoint_sha256']and parent['sha256']not in seen,'cache ancestry parent/cycle differs')
        seen.add(parent['sha256'])
        if parent==receipt['old_checkpoint_manifest']:
            need(node['model_state']==receipt['derivative_model_checkpoint']
                and node['optimizer_state']==receipt['derivative_optimizer_checkpoint']
                and progress==receipt['original_progress'],'cache root numerical pair/progress differs')
            break
        later=progress['optimizer_steps']
        node,raw=_reviewed_epoch_document(parent,limit=4*1024**2);observed.append((parent,raw))
        need(sum(len(raw)for _,raw in observed)<=16*1024**2,'cache ancestry metadata byte capacity exceeded')
    else:raise TrainingJobValidationError('cache ancestry depth capacity exceeded')
    for parent,raw in observed:
        need(_reviewed_decoder_artifact(CheckpointArtifact.from_dict(parent),limit=4*1024**2)==raw,'cache ancestry changed during replay')
    normalized=dict(latest,schema=REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA)
    for key in extra:normalized.pop(key)
    return normalized


REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA = 'reviewed-mixed-digest-omitted-cache-source-job/v1'
_REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_FIELDS = frozenset({'schema', 'profile', 'old_checkpoint_manifest', 'old_configuration_artifact', 'old_pipeline_artifact', 'current_configuration_artifact', 'source_contract_artifact', 'current_pipeline_artifact', 'derivative_model_checkpoint', 'derivative_optimizer_checkpoint', 'target_job_spec', 'migrated_training_binding', 'original_progress', 'pipeline_proof', 'source_projection_sha256', 'dependency_scope', 'historical_dependency_execution_requalified', 'model_Adam_steps_RNG_and_progress_preserved', 'qualified', 'promotion_performed', 'legal_meaning_verified', 'convergence_proved', 'corpus_admitted', 'new_checkpoint_lineage_id', 'new_base_version_id', 'origin_kind', 'training_resume_eligible'})


def _reviewed_digest_cache_epoch_marker(origin_sha256, current_source_sha256, population_sha256, *, _profile=REVIEWED_DIGEST_CACHE_EPOCH_PROFILE):
    _reviewed_epoch_need(_profile in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE),'closed digest cache marker profile required')
    _reviewed_epoch_need(type(origin_sha256)is type(population_sha256)is str
        and re.fullmatch('[0-9a-f]{64}',origin_sha256)is not None
        and re.fullmatch('[0-9a-f]{64}',population_sha256)is not None
        and type(current_source_sha256)is dict and set(current_source_sha256)==REVIEWED_DECODER_SOURCE_NAMES
        and all(type(value)is str and re.fullmatch('[0-9a-f]{64}',value)is not None for value in current_source_sha256.values()),
        'exact source/parent/population marker commitments required')
    version=_digest(_json_bytes({'profile':_profile,
        'old_manifest':origin_sha256,'current_source':current_source_sha256,'population':population_sha256}))
    return {'schema':'reviewed-digest-cache-source-marker/v1','profile':_profile,
        'origin_checkpoint_sha256':origin_sha256,'lineage_sha256':version}


def _reviewed_digest_cache_epoch_validate_marker(value):
    _reviewed_epoch_need(type(value)is dict and set(value)=={'schema','profile','origin_checkpoint_sha256','lineage_sha256'}
        and value['schema']=='reviewed-digest-cache-source-marker/v1'
        and value['profile'] in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE)
        and all(type(value[key])is str and re.fullmatch('[0-9a-f]{64}',value[key])is not None
            for key in('origin_checkpoint_sha256','lineage_sha256')),'closed immutable digest cache marker required')
    return dict(value)


def _reviewed_digest_cache_epoch_require_job(spec, backend):
    _reviewed_epoch_need(type(spec)is ReviewedDigestCacheEpochTrainingJobSpec
        and type(backend)is TorchReviewedDecoderBackend
        and backend.cache_source_epoch_marker is not None,
        'marked numeric pair requires explicit typed cache receipt and ancestry job')
    _reviewed_digest_cache_epoch_validate_marker(_thaw(backend.cache_source_epoch_marker))


def _reviewed_digest_cache_epoch_load_receipt(reference, expected_identity, expected_pins, expected_admission):
    """Pre-model receipt/context proof; numerical receipt proof follows restore."""
    need=_reviewed_epoch_need
    need(type(reference)is CheckpointArtifact,'explicit exact cache receipt artifact required for marked loader')
    receipt,_=_reviewed_epoch_document(asdict(reference),limit=8*1024**2)
    profile=receipt.get('profile') if type(receipt)is dict else None
    context_builder=_reviewed_digest_cache_epoch_context_for_profile(profile)
    fields=_REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_FIELDS
    need(type(receipt)is dict and set(receipt)==fields
        and receipt['schema']==REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA
        and receipt['profile']==profile
        and receipt['training_resume_eligible']is True and receipt['origin_kind']==('pristine0' if profile==REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE else 'trained3')
        and receipt['historical_dependency_execution_requalified']is False
        and receipt['model_Adam_steps_RNG_and_progress_preserved']is True
        and all(receipt[key]is False for key in('qualified','promotion_performed','legal_meaning_verified','convergence_proved','corpus_admitted')),
        'closed nonauthorizing cache receipt required before marked construction')
    spec=ReviewedDigestOmittedDecoderTrainingJobSpec.from_dict(receipt['target_job_spec'])
    context=context_builder(spec,
        CheckpointArtifact.from_dict(receipt['old_configuration_artifact']),
        CheckpointArtifact.from_dict(receipt['old_pipeline_artifact']),
        CheckpointArtifact.from_dict(receipt['current_configuration_artifact']),
        CheckpointArtifact.from_dict(receipt['source_contract_artifact']))
    need(receipt['old_checkpoint_manifest']==asdict(spec.parent_checkpoint_artifact)
        and receipt['new_checkpoint_lineage_id']==context['new_checkpoint_lineage_id']
        and receipt['new_base_version_id']==context['new_base_version_id']
        and receipt['original_progress']==context['old_manifest']['progress']
        and _thaw(spec.backend_identity)==expected_identity
        and _thaw(spec.expected_source_sha256)==expected_pins
        and spec.expected_admission_inputs_sha256==expected_admission,
        'marked load receipt/context/source/admission differs')
    return _reviewed_digest_cache_epoch_validate_marker(context['current_configuration']['cache_source_epoch_marker'])


def _reviewed_digest_cache_epoch_fresh_admission(spec, current_admission_provider, binding):
    # Import the already-pinned ordinary owner before the LAST external callback.
    from . import legal_span_consumer_binding as consumer
    fresh=current_admission_provider()
    actual=consumer.reviewed_admission_inputs_sha256(fresh)
    _reviewed_epoch_need(actual==spec.expected_admission_inputs_sha256
        and actual==binding['admission_inputs_sha256'],
        'current digest admission revoked after final execution callback')



def _reviewed_digest_cache_epoch_artifact_inventory(spec, context, model, optimizer, pipeline, receipt, manifest, state_cap):
    """Finite explicit files read by this migration and its public preparation.

    Capture before the last external callback. No new registry interface or
    interpretation of arbitrary document-shaped references is introduced.
    """
    from ...logic.autoformal import training_cycle_inputs as inputs
    from ...logic.autoformal import legal_reviewed_norm_admission_v3 as admission
    from . import legal_span_consumer_binding as consumer, legal_ir_eval_splits as splits
    need=_reviewed_epoch_need
    need(type(state_cap)is int and state_cap==2*1024**3,'validated omitted-Qwen state cap required')
    rows={}
    stamp=lambda info:tuple(getattr(info,key)for key in('st_dev','st_ino','st_mode','st_nlink','st_uid','st_gid','st_size','st_mtime_ns','st_ctime_ns'))
    def add(reference, limit):
        reference=reference if type(reference)is CheckpointArtifact else CheckpointArtifact.from_dict(reference)
        path=Path(reference.path)
        existing=rows.get(reference.path)
        if existing is not None:
            need(existing[0]==reference,'one physical artifact has conflicting commitments')
            return
        need(len(rows)<128,'finite explicit artifact inventory capacity exceeded')
        before=stamp(path.lstat())
        _reviewed_decoder_artifact(reference,limit=limit,load=False)
        after=stamp(path.lstat())
        need(before==after,'artifact inventory changed during initial authentication')
        rows[reference.path]=(reference,limit,after)
    for reference in(spec.base_model_checkpoint,spec.base_optimizer_checkpoint,model,optimizer):add(reference,state_cap)
    for reference in(spec.model_artifact,*spec.backend_artifacts):add(reference,state_cap)
    for reference in(spec.tokenizer_artifact,spec.license_artifact):add(reference,MAX_CHECKPOINT_BYTES)
    for reference,limit in((spec.parent_checkpoint_artifact,4*1024**2),
        (context['old_configuration_artifact'],4*1024**2),(context['current_configuration_artifact'],4*1024**2),
        (context['old_pipeline_artifact'],MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES),
        (context['source_contract_artifact'],2*1024**2),(pipeline,MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES),
        (receipt,8*1024**2),(manifest,4*1024**2),
        (context['contract']['old_training_binding_artifact'],4*1024**2),
        (context['contract']['dependency_snapshot_artifact'],1024**2)):
        add(reference,limit)
    for key in('old_source_artifacts','current_source_artifacts'):
        for reference in context['contract'][key].values():add(reference,2*1024**2)
    dependency,_=_reviewed_epoch_document(context['contract']['dependency_snapshot_artifact'],limit=1024**2)
    for reference in dependency['implementation'].values():add(reference,16*1024**2)
    modules={'worker':__file__,'inputs':inputs.__file__,'consumer':consumer.__file__,
        'admission':admission.__file__,'splits':splits.__file__}
    for key,path in modules.items():
        add({'path':str(Path(path)),'bytes':Path(path).lstat().st_size,
            'sha256':_thaw(spec.expected_source_sha256)[key]},MAX_CHECKPOINT_BYTES)
    for reference in(spec.exposure_artifact,spec.source_contexts_artifact):add(reference,inputs.MAX_REVIEWED_ARTIFACT_BYTES)
    # These are exactly the stage/parent references read by the existing
    # _prepare_reviewed_decoder_training_inputs path; rows are not interpreted.
    add(spec.stage_artifact,inputs.MAX_REVIEWED_ARTIFACT_BYTES)
    stage=_parse_json(_reviewed_decoder_artifact(spec.stage_artifact,limit=inputs.MAX_REVIEWED_ARTIFACT_BYTES))
    def add_transport(reference):
        add(reference,inputs.MAX_REVIEWED_ARTIFACT_BYTES)
        value=_parse_json(_reviewed_decoder_artifact(CheckpointArtifact.from_dict(reference),limit=inputs.MAX_REVIEWED_ARTIFACT_BYTES))
        need(value['schema']=='reviewed-cycle-admission-input-transport/v2','exact owned admission transport required')
        for leaf in value['byte_leaves']:
            if leaf['kind']=='artifact_bytes':add(leaf['artifact'],inputs.MAX_REVIEWED_ARTIFACT_BYTES)
    for key in('rows_artifact','split_manifest_artifact','history_artifact'):
        add(stage[key],inputs.MAX_REVIEWED_ARTIFACT_BYTES)
    if stage.get('admission_transport_artifact')is not None:add_transport(stage['admission_transport_artifact'])
    if stage['parent_artifact']is not None:
        parent_ref=CheckpointArtifact.from_dict(stage['parent_artifact']);add(parent_ref,inputs.MAX_REVIEWED_ARTIFACT_BYTES)
        parent=_parse_json(_reviewed_decoder_artifact(parent_ref,limit=inputs.MAX_REVIEWED_ARTIFACT_BYTES))
        for key in('rows_artifact','history_artifact'):
            if parent.get(key)is not None:add(parent[key],inputs.MAX_REVIEWED_ARTIFACT_BYTES)
        if parent.get('admission_transport_artifact')is not None:add_transport(parent['admission_transport_artifact'])
    return tuple(rows.values())


def _reviewed_digest_cache_epoch_close_artifacts(inventory):
    """After the final provider: plain bounded reader/full9 checks ONLY."""
    stamp=lambda info:tuple(getattr(info,key)for key in('st_dev','st_ino','st_mode','st_nlink','st_uid','st_gid','st_size','st_mtime_ns','st_ctime_ns'))
    closed=[]
    for reference,limit,initial in inventory:
        path=Path(reference.path)
        _reviewed_epoch_need(stamp(path.lstat())==initial,'immutable artifact changed after final provider')
        _reviewed_decoder_artifact(reference,limit=limit,load=False)
        _reviewed_epoch_need(stamp(path.lstat())==initial,'immutable artifact changed during final byte closure')
        closed.append({'artifact':asdict(reference),'per_file_byte_limit':limit,
            'full9_before_final_provider':[str(value)for value in initial],
            'full9_and_SHA_equal_after_final_provider':True})
    return {'schema':'reviewed-digest-cache-source-artifact-finalization/v1',
        'artifacts':closed,'artifact_count':len(closed),'all_bound_bytes_and_full9_unchanged':True,
        'live_backend_returned':False,'live_state_at_return_verified':False,
        'scope':'Numerical equality was verified before final provider and transfers only to unchanged authenticated published bytes. A discarded live object is not part of this result.'}
@dataclass(frozen=True)
class ReviewedDigestCacheEpochTrainingJobSpec(ReviewedDigestOmittedDecoderTrainingJobSpec):
    """Explicit same-objective cache epoch; receipt identity is a real field."""
    cache_source_epoch_migration: CheckpointArtifact = field(kw_only=True)
    schema_version: str = REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA

    def __post_init__(self):
        if type(self.cache_source_epoch_migration) is not CheckpointArtifact:
            raise TrainingJobValidationError('exact mandatory digest cache migration receipt required')
        super().__post_init__()

    @classmethod
    def from_dict(cls, value):
        data = dict(_object(value, {item.name for item in fields(cls)}, 'digest cache source job'))
        data['cache_source_epoch_migration'] = CheckpointArtifact.from_dict(data.get('cache_source_epoch_migration'))
        return super().from_dict(data)

    def to_dict(self):
        value = super().to_dict()
        value['cache_source_epoch_migration'] = asdict(self.cache_source_epoch_migration)
        return value

def _reviewed_digest_cache_epoch_loader_context(context, model_checkpoint, optimizer_checkpoint, backend_identity, source_pins, admission_sha):
    _reviewed_epoch_need(type(context) is dict and context.get('profile') in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE), 'explicit same-digest cache migration context required')
    checked = _reviewed_digest_cache_epoch_context_for_profile(context['profile'])(context['spec'], CheckpointArtifact.from_dict(context['old_configuration_artifact']), CheckpointArtifact.from_dict(context['old_pipeline_artifact']), CheckpointArtifact.from_dict(context['current_configuration_artifact']), CheckpointArtifact.from_dict(context['source_contract_artifact']))
    spec = checked['spec']
    _reviewed_epoch_need(set(context) == set(checked) and all((context[key] == checked[key] for key in checked)) and (spec.base_model_checkpoint == model_checkpoint) and (spec.base_optimizer_checkpoint == optimizer_checkpoint) and (_thaw(spec.backend_identity) == backend_identity) and (_thaw(spec.expected_source_sha256) == source_pins) and (spec.expected_admission_inputs_sha256 == admission_sha), 'cache loader request/context is not the exact authenticated migration spec')
    context.clear()
    context.update(checked)

def _reviewed_epoch_family_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current, *, _family):
    """Existing paired transfer with exact equality, new proof, no numeric updates."""
    if _family == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:
        _context_builder, _prepare_binding, _binding_proof = (_reviewed_train_resume_epoch_context, _reviewed_epoch_prepare_binding, _reviewed_epoch_binding_proof)
    elif _family == REVIEWED_DIGEST_CACHE_EPOCH_PROFILE:
        _context_builder, _prepare_binding, _binding_proof = (_reviewed_digest_cache_epoch_context, _reviewed_digest_cache_epoch_prepare_binding, _reviewed_digest_cache_epoch_binding_proof)
    elif _family == REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE:
        _context_builder, _prepare_binding, _binding_proof = (_reviewed_digest_cache_pristine_epoch_context, _reviewed_digest_cache_epoch_prepare_binding, _reviewed_digest_cache_epoch_binding_proof)
    else:
        raise TrainingJobValidationError('closed existing migration family required')
    from collections import OrderedDict
    _reviewed_epoch_need(type(backend) is TorchReviewedDecoderBackend, 'exact current backend required')
    spec = context['spec']
    checked = _context_builder(spec, CheckpointArtifact.from_dict(context['old_configuration_artifact']), CheckpointArtifact.from_dict(context['old_pipeline_artifact']), CheckpointArtifact.from_dict(context['current_configuration_artifact']), CheckpointArtifact.from_dict(context['source_contract_artifact']))
    context.clear()
    context.update(checked)
    current()
    _reviewed_epoch_need(_json_bytes(backend._configuration()) == _json_bytes(context['current_configuration']), 'constructed TRAIN-resume current configuration differs')
    _reviewed_epoch_authenticate_assets(spec, backend)
    current_raw = backend.tokenizer.pipeline_serialization()
    proof = _reviewed_epoch_pipeline_proof(context['old_pipeline_raw'], current_raw, context['sources'], context['contract']['old_source_sha256'], context['contract']['current_source_sha256'])
    _reviewed_epoch_need(proof['current_contract'] == context['current_configuration']['tokenizer'] and proof['current_binding'] == context['current_configuration']['tokenizer_binding'], 'actual new pipeline/config identity differs')
    dependency = _reviewed_epoch_family_dependencies(context,backend,_family=_family)
    prepared = _prepare_binding(spec, registry, backend.tokenizer, current_admission_provider)
    _binding_proof(context['old_population_binding'], prepared['receipt'], context['contract'])
    _reviewed_epoch_need(prepared['receipt']['tokenizer_contract'] == proof['current_contract'], 'current same-T3 input preparation differs')
    current()
    model, optimizer = _reviewed_epoch_old_pair(backend, model_raw, optimizer_raw, context['old_configuration'], context['old_manifest']['progress']['optimizer_steps'])
    _reviewed_epoch_need(bool(optimizer['state']['state']) == (context['origin_kind'] == 'trained3'), 'pristine must have empty Adam; trained3 must retain actual nonempty Adam')
    state = OrderedDict(model['state'])
    state._metadata = model['state_metadata']
    backend.model.load_state_dict(state, strict=True)
    current()
    backend.optimizer.load_state_dict(optimizer['state'])
    current()
    backend._torch().set_rng_state(optimizer['cpu_rng'])
    backend._optimizer_steps = optimizer['optimizer_steps']
    current()
    live_model = backend._model_state()
    live_optimizer = {'state': backend.optimizer.state_dict(), 'optimizer_steps': backend._optimizer_steps, 'cpu_rng': backend._torch().get_rng_state(), 'device_rng': None}
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend, model, optimizer, live_model, live_optimizer), 'TRAIN-resume bridge actual model/Adam/RNG transfer differs')
    derivative = backend.snapshot_checkpoint()
    new_model, new_optimizer = backend._load_pair(derivative['model_state'], derivative['optimizer_state'])
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend, model, optimizer, new_model, new_optimizer), 'TRAIN-resume new-format pair changed actual numerical halves or progress')
    current()
    _reviewed_epoch_need(backend.tokenizer.pipeline_serialization() == current_raw and _reviewed_epoch_family_dependencies(context,backend,_family=_family) == dependency, 'current pipeline/runtime cohort changed during transfer')
    context.update(current_pipeline_raw=current_raw, current_training_binding=prepared['receipt'], pipeline_proof=proof, derivative_pair=derivative, dependency_scope=_reviewed_epoch_family_dependency_scope(context,_family=_family))
    return (derivative['model_state'], derivative['optimizer_state'])

def _reviewed_epoch_family_validate_receipt(reference, backend, *, expected_spec=None, _family):
    """Recompute every proof and actual old/current pair; no receipt-only waiver."""
    if _family == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:
        _receipt_schema, _profile, _receipt_spec, _expected_spec_type, _context_builder, _binding_proof = (REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA, REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE, _reviewed_epoch_receipt_spec, ReviewedMixedDecoderTrainingJobSpec, _reviewed_train_resume_epoch_context, _reviewed_epoch_binding_proof)
    elif _family == REVIEWED_DIGEST_CACHE_EPOCH_PROFILE:
        _receipt_schema, _profile, _receipt_spec, _expected_spec_type, _context_builder, _binding_proof = (REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA, REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, _reviewed_digest_cache_epoch_receipt_spec, ReviewedDigestCacheEpochTrainingJobSpec, _reviewed_digest_cache_epoch_context, _reviewed_digest_cache_epoch_binding_proof)
    elif _family == REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE:
        _receipt_schema, _profile, _receipt_spec, _expected_spec_type, _context_builder, _binding_proof = (REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE, _reviewed_digest_cache_epoch_receipt_spec, ReviewedDigestCacheEpochTrainingJobSpec, _reviewed_digest_cache_pristine_epoch_context, _reviewed_digest_cache_epoch_binding_proof)
    else:
        raise TrainingJobValidationError('closed existing migration family required')
    receipt, _ = _reviewed_epoch_document(reference, limit=8 * 1024 ** 2)
    fields = {'schema', 'profile', 'old_checkpoint_manifest', 'old_configuration_artifact', 'old_pipeline_artifact', 'current_configuration_artifact', 'source_contract_artifact', 'current_pipeline_artifact', 'derivative_model_checkpoint', 'derivative_optimizer_checkpoint', 'target_job_spec', 'migrated_training_binding', 'original_progress', 'pipeline_proof', 'source_projection_sha256', 'dependency_scope', 'historical_dependency_execution_requalified', 'model_Adam_steps_RNG_and_progress_preserved', 'qualified', 'promotion_performed', 'legal_meaning_verified', 'convergence_proved', 'corpus_admitted', 'new_checkpoint_lineage_id', 'new_base_version_id', 'origin_kind', 'training_resume_eligible'}
    _reviewed_epoch_need(type(receipt) is dict and set(receipt) == fields and (receipt['schema'] == _receipt_schema) and (receipt['profile'] == _profile) and (receipt['training_resume_eligible'] is True) and (receipt['historical_dependency_execution_requalified'] is False) and (receipt['model_Adam_steps_RNG_and_progress_preserved'] is True) and all((receipt[key] is False for key in ('qualified', 'promotion_performed', 'legal_meaning_verified', 'convergence_proved', 'corpus_admitted'))), 'closed nonauthorizing TRAIN-resume migration receipt required')
    spec = _receipt_spec(receipt, None, backend)
    if expected_spec is not None:
        _reviewed_epoch_need(type(expected_spec) is _expected_spec_type, 'explicit TRAIN-resume target spec required')
        original_spec, next_spec = (spec.to_dict(), expected_spec.to_dict())
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            _reviewed_epoch_need(next_spec.pop('cache_source_epoch_migration') == asdict(CheckpointArtifact.from_dict(reference)) and next_spec['schema_version'] == REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA, 'typed cache resume receipt/schema differs')
            next_spec['schema_version'] = original_spec['schema_version']
        mutable = {'job_id', 'run_id', 'output_directory', 'max_steps', 'max_seconds', 'parent_checkpoint_artifact', 'base_model_checkpoint', 'base_optimizer_checkpoint', 'checkpoint_lineage_id', 'base_version_id'}
        _reviewed_epoch_need(set(original_spec) == set(next_spec) and all((original_spec[key] == next_spec[key] for key in original_spec if key not in mutable)), 'TRAIN-resume numerical/data/context/configuration target changed')
    _reviewed_epoch_need(asdict(spec.parent_checkpoint_artifact) == receipt['old_checkpoint_manifest'], 'TRAIN-resume original pair metadata changed')
    context = _context_builder(spec, CheckpointArtifact.from_dict(receipt['old_configuration_artifact']), CheckpointArtifact.from_dict(receipt['old_pipeline_artifact']), CheckpointArtifact.from_dict(receipt['current_configuration_artifact']), CheckpointArtifact.from_dict(receipt['source_contract_artifact']))
    if expected_spec is not None:
        _reviewed_epoch_need(expected_spec.checkpoint_lineage_id == context['new_checkpoint_lineage_id'] and expected_spec.base_version_id == context['new_base_version_id'], 'TRAIN-resume target lineage/version differs')
    _reviewed_epoch_need(receipt['new_checkpoint_lineage_id'] == context['new_checkpoint_lineage_id'] and receipt['new_base_version_id'] == context['new_base_version_id'] and (receipt['origin_kind'] == context['origin_kind']) and (receipt['original_progress'] == context['old_manifest']['progress']) and (receipt['dependency_scope'] == _reviewed_epoch_family_dependency_scope(context,_family=_family)), 'TRAIN-resume lineage/version/original progress/scope differs')
    _reviewed_epoch_authenticate_assets(spec, backend)
    _reviewed_epoch_need(_json_bytes(backend._configuration()) == _json_bytes(context['current_configuration']), 'TRAIN-resume live complete config changed')
    current_raw = _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt['current_pipeline_artifact']), limit=MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES)
    _reviewed_epoch_need(current_raw == backend.tokenizer.pipeline_serialization(), 'new actual tokenizer pipeline changed')
    proof = _reviewed_epoch_pipeline_proof(context['old_pipeline_raw'], current_raw, context['sources'], context['contract']['old_source_sha256'], context['contract']['current_source_sha256'])
    _reviewed_epoch_need(proof == receipt['pipeline_proof'] and receipt['source_projection_sha256'] == context['sources']['projection_sha256'], 'TRAIN-resume pipeline/Source proof differs')
    _binding_proof(context['old_population_binding'], receipt['migrated_training_binding'], context['contract'])
    _reviewed_epoch_need(receipt['migrated_training_binding']['tokenizer_contract'] == proof['current_contract'], 'TRAIN-resume new population pipeline differs')
    _reviewed_epoch_family_dependencies(context,backend,_family=_family)
    limit = backend._checkpoint_byte_limit()
    old_model, old_optimizer = _reviewed_epoch_old_pair(backend, _reviewed_decoder_artifact(spec.base_model_checkpoint, limit=limit), _reviewed_decoder_artifact(spec.base_optimizer_checkpoint, limit=limit), context['old_configuration'], context['old_manifest']['progress']['optimizer_steps'])
    _reviewed_epoch_need(bool(old_optimizer['state']['state']) == (context['origin_kind'] == 'trained3'), 'TRAIN-resume old Adam origin mismatch')
    new_model, new_optimizer = backend._load_pair(_reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt['derivative_model_checkpoint']), limit=limit), _reviewed_decoder_artifact(CheckpointArtifact.from_dict(receipt['derivative_optimizer_checkpoint']), limit=limit))
    _reviewed_epoch_need(_reviewed_epoch_pair_equal(backend, old_model, old_optimizer, new_model, new_optimizer), 'TRAIN-resume actual old/new model/Adam/RNG/progress differ')
    return receipt

def _migrate_local_reviewed_decoder_epoch_family(spec, *, registry, current_admission_provider, execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact, tokenizer_artifact, license_artifact, old_configuration_artifact, old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact, output_directory, max_model_bytes, runtime_profile='builtin-qwen2-bfloat16/v1', _family):
    """Migrate the exact original9d TRAIN3 pair to a NEW current train-resume version.

    Actual old pipeline and current dependency-cohort snapshots must be captured
    BEFORE Source adoption. No fresh vendor import, fitting, counter/RNG reset,
    old-artifact rewrite, promotion or historical dependency requalification.
    The caller retains existing execution/resource/asset/admission ownership.
    """
    if _family == REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE:
        _migration_spec_type, _context_builder, _profile, _receipt_schema, _validate_receipt, _load_current, _next_type, _prepare_binding = (ReviewedMixedDecoderTrainingJobSpec, _reviewed_train_resume_epoch_context, REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE, REVIEWED_DECODER_TRAIN_RESUME_EPOCH_RECEIPT_SCHEMA, _reviewed_train_resume_epoch_validate_receipt, load_local_reviewed_decoder_runtime_v3, ReviewedMixedDecoderTrainingJobSpec, _reviewed_epoch_prepare_binding)
    elif _family == REVIEWED_DIGEST_CACHE_EPOCH_PROFILE:
        _migration_spec_type, _context_builder, _profile, _receipt_schema, _validate_receipt, _load_current, _next_type, _prepare_binding = (ReviewedDigestOmittedDecoderTrainingJobSpec, _reviewed_digest_cache_epoch_context, REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA, _reviewed_digest_cache_epoch_validate_receipt, load_local_reviewed_decoder_digest_omitted_runtime_v1, ReviewedDigestCacheEpochTrainingJobSpec, _reviewed_digest_cache_epoch_prepare_binding)
    elif _family == REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE:
        _migration_spec_type, _context_builder, _profile, _receipt_schema, _validate_receipt, _load_current, _next_type, _prepare_binding = (ReviewedDigestOmittedDecoderTrainingJobSpec, _reviewed_digest_cache_pristine_epoch_context, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA, _reviewed_digest_cache_epoch_validate_receipt, load_local_reviewed_decoder_digest_omitted_runtime_v1, ReviewedDigestCacheEpochTrainingJobSpec, _reviewed_digest_cache_epoch_prepare_binding)
    else:
        raise TrainingJobValidationError('closed existing migration family required')
    import gc
    import stat
    _reviewed_epoch_need(runtime_profile == 'builtin-qwen2-bfloat16/v1' and all((callable(value) for value in (current_admission_provider, execution_guard, asset_policy_guard))), 'existing live guards required')
    _reviewed_epoch_need(type(spec) is _migration_spec_type and tokenizer_artifact == spec.tokenizer_artifact and (license_artifact == spec.license_artifact) and (recipe_artifact in spec.backend_artifacts) and (model_config_artifact in spec.backend_artifacts) and (recipe_artifact != model_config_artifact), 'loader recipe/configuration/tokenizer/license must be the exact declared old assets')
    execution_guard()
    policy = {'schema': 'reviewed-decoder-source-epoch-migration-policy/v1', 'target_job_spec': spec.to_dict(), 'old_configuration': asdict(old_configuration_artifact), 'old_pipeline': asdict(old_tokenizer_pipeline_artifact), 'current_configuration': asdict(current_configuration_artifact), 'source_contract': asdict(compatibility_contract_artifact), 'profile': _profile, 'migration_requested': True, 'training_resume_requested': True, 'training_requested': False, 'downloads_requested': False, 'resource_grant_requested': False, 'promotion_requested': False}
    asset_policy_guard(_parse_json(_json_bytes(policy)))
    context = _context_builder(spec, old_configuration_artifact, old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact)
    output = Path(output_directory)
    _reviewed_epoch_need(output.is_absolute() and (not os.path.lexists(output)) and (output.parent.resolve(strict=True) == output.parent) and (output != Path(spec.output_directory)) and all((stat.S_ISDIR(parent.lstat().st_mode) for parent in output.parents)), 'distinct fresh ordinary migration output directory required')
    import torch
    entry_rng = torch.get_rng_state().clone()
    succeeded = False
    try:
        runtime, internal_receipt = _load_local_reviewed_decoder_runtime(registry=registry, current_admission_provider=current_admission_provider, execution_guard=execution_guard, asset_policy_guard=asset_policy_guard, recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact, tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact, model_checkpoint=spec.base_model_checkpoint, optimizer_checkpoint=spec.base_optimizer_checkpoint, expected_backend_identity=_thaw(spec.backend_identity), expected_source_sha256=_thaw(spec.expected_source_sha256), expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256, max_model_bytes=max_model_bytes, _admission_version='v3', _runtime_profile=runtime_profile, _source_epoch_migration=context, **{'_target_codec': REVIEWED_DIGEST_OMITTED_TARGET_CODEC} if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) else {})
        execution_guard()
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(context['derivative_pair']['model_state'], context['derivative_pair']['optimizer_state']), 'current pair changed before publication')
        output.mkdir(mode=448, exist_ok=False)
        model = _write_exclusive(output / 'model.checkpoint', context['derivative_pair']['model_state'])
        optimizer = _write_exclusive(output / 'optimizer.checkpoint', context['derivative_pair']['optimizer_state'])
        pipeline = _write_exclusive(output / 'current-tokenizer-pipeline.json', context['current_pipeline_raw'])
        receipt = {'schema': _receipt_schema, 'profile': _profile, 'old_checkpoint_manifest': asdict(spec.parent_checkpoint_artifact), 'old_configuration_artifact': context['old_configuration_artifact'], 'old_pipeline_artifact': context['old_pipeline_artifact'], 'current_configuration_artifact': context['current_configuration_artifact'], 'source_contract_artifact': context['source_contract_artifact'], 'current_pipeline_artifact': pipeline, 'derivative_model_checkpoint': model, 'derivative_optimizer_checkpoint': optimizer, 'target_job_spec': spec.to_dict(), 'migrated_training_binding': context['current_training_binding'], 'original_progress': context['old_manifest']['progress'], 'new_checkpoint_lineage_id': context['new_checkpoint_lineage_id'], 'new_base_version_id': context['new_base_version_id'], 'origin_kind': context['origin_kind'], 'training_resume_eligible': True, 'pipeline_proof': context['pipeline_proof'], 'source_projection_sha256': context['sources']['projection_sha256'], 'dependency_scope': context['dependency_scope'], 'historical_dependency_execution_requalified': False, 'model_Adam_steps_RNG_and_progress_preserved': True, 'qualified': False, 'promotion_performed': False, 'legal_meaning_verified': False, 'convergence_proved': False, 'corpus_admitted': False}
        receipt_ref = _write_exclusive(output / 'source-epoch-TRAIN-resume-migration.json', _json_bytes(receipt))
        original = context['old_manifest']
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            manifest = {**original, 'schema': REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA, 'checkpoint_lineage_id': context['new_checkpoint_lineage_id'], 'base_version_id': context['new_base_version_id'], 'backend_identity': _thaw(spec.backend_identity), 'producer_pins': _thaw(spec.expected_source_sha256), 'training_binding': context['current_training_binding'], 'model_state': model, 'optimizer_state': optimizer, 'token_budgets': {'max_source_tokens': spec.max_source_tokens, 'max_target_tokens': spec.max_target_tokens, 'tokenizer_contract': context['current_training_binding']['tokenizer_contract']}, 'parent_checkpoint_sha256': spec.parent_checkpoint_artifact.sha256, 'cache_source_epoch_migration': receipt_ref, 'cache_epoch_parent_checkpoint_artifact': asdict(spec.parent_checkpoint_artifact)}
        else:
            manifest = {**original, 'schema': REVIEWED_DECODER_SOURCE_EPOCH_CHECKPOINT_SCHEMA, 'checkpoint_lineage_id': context['new_checkpoint_lineage_id'], 'base_version_id': context['new_base_version_id'], 'backend_identity': _thaw(spec.backend_identity), 'producer_pins': _thaw(spec.expected_source_sha256), 'training_binding': context['current_training_binding'], 'model_state': model, 'optimizer_state': optimizer, 'token_budgets': {'max_source_tokens': spec.max_source_tokens, 'max_target_tokens': spec.max_target_tokens, 'tokenizer_contract': context['current_training_binding']['tokenizer_contract']}, 'parent_checkpoint_sha256': spec.parent_checkpoint_artifact.sha256, 'continuation_profile': spec.continuation_profile, 'optimizer_step_offset': 0, 'stage_continuation': None, 'source_epoch_migration': receipt_ref}
        manifest_ref = _write_exclusive(output / 'reviewed-decoder-checkpoint.json', _json_bytes(manifest))
        del runtime
        context.pop('derivative_pair')
        gc.collect()
        runtime, load_receipt = _load_current(admission_profile=spec.admission_profile, registry=registry, current_admission_provider=current_admission_provider, execution_guard=execution_guard, asset_policy_guard=asset_policy_guard, recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact, tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact, model_checkpoint=CheckpointArtifact.from_dict(model), optimizer_checkpoint=CheckpointArtifact.from_dict(optimizer), expected_backend_identity=_thaw(spec.backend_identity), expected_source_sha256=_thaw(spec.expected_source_sha256), expected_admission_inputs_sha256=spec.expected_admission_inputs_sha256, max_model_bytes=max_model_bytes, runtime_profile=runtime_profile, **{'cache_source_epoch_migration': CheckpointArtifact.from_dict(receipt_ref)} if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) else {})
        _validate_receipt(receipt_ref, runtime.backend, expected_spec=None)
        prepared = _prepare_binding(spec, registry, runtime.tokenizer, current_admission_provider)
        _reviewed_epoch_need(prepared['receipt'] == context['current_training_binding'], 'ordinary current admission/input binding changed after derivative reload')
        new_spec = spec.to_dict()
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            new_spec.update(schema_version=REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA, cache_source_epoch_migration=receipt_ref)
        new_spec.update(checkpoint_lineage_id=context['new_checkpoint_lineage_id'], base_version_id=context['new_base_version_id'], parent_checkpoint_artifact=manifest_ref, base_model_checkpoint=model, base_optimizer_checkpoint=optimizer)
        _validate_receipt(receipt_ref, runtime.backend, expected_spec=_next_type.from_dict(new_spec))
        result = {'schema': 'reviewed-digest-omitted-cache-source-artifact-migration-operation/v1' if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) else 'reviewed-decoder-TRAIN-resume-source-epoch-migration-operation/v1', 'training_resume_eligible': True, 'new_checkpoint_lineage_id': context['new_checkpoint_lineage_id'], 'new_base_version_id': context['new_base_version_id'], 'migration_receipt': receipt_ref, 'candidate': manifest_ref, 'model_checkpoint': model, 'optimizer_checkpoint': optimizer, 'next_job_spec': new_spec, 'worker_progress': dict(original['progress']), 'ordinary_current_loader': load_receipt, 'qualified': False, 'promotion_performed': False, 'training_performed': False, 'resource_granted': False, 'historical_dependency_execution_requalified': False}
        execution_guard()
        _validate_receipt(receipt_ref, runtime.backend, expected_spec=None)
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            prepared = _prepare_binding(spec, registry, runtime.tokenizer, current_admission_provider)
        _reviewed_epoch_need(runtime.backend.restored_checkpoint_matches(_reviewed_decoder_artifact(CheckpointArtifact.from_dict(model), limit=runtime.backend._checkpoint_byte_limit()), _reviewed_decoder_artifact(CheckpointArtifact.from_dict(optimizer), limit=runtime.backend._checkpoint_byte_limit())), 'live derivative pair changed during final callback/provenance validation')
        _reviewed_epoch_need(runtime.backend.identity() == _thaw(spec.backend_identity) and _reviewed_decoder_source_pins(admission_profile=spec.admission_profile) == _thaw(spec.expected_source_sha256), 'current backend or Source changed before migration publication')
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            _reviewed_epoch_need(prepared['receipt'] == context['current_training_binding'], 'final current digest binding changed')
            final_inventory = _reviewed_digest_cache_epoch_artifact_inventory(spec, context, model, optimizer, pipeline, receipt_ref, manifest_ref, runtime.backend._checkpoint_byte_limit())
            del runtime
            gc.collect()
            _reviewed_digest_cache_epoch_fresh_admission(spec, current_admission_provider, prepared['receipt'])
            result['immutable_artifact_finalization'] = _reviewed_digest_cache_epoch_close_artifacts(final_inventory)
            result.update(artifact_only=True, live_runtime_returned=False, live_runtime_state_at_return_claimed=False, requires_validated_profile_reload=True, numerical_pair_verified_before_final_provider=True, final_current_admission_and_binding_rechecked=True)
        _write_exclusive(output / 'receipt.json', _json_bytes(result))
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        succeeded = True
        if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE):
            return result
        return (runtime, result)
    except BaseException as error:
        if output.exists():
            try:
                _write_exclusive(output / 'failure.json', _json_bytes({'schema': 'reviewed-digest-omitted-cache-source-migration-failure/v1' if _family in (REVIEWED_DIGEST_CACHE_EPOCH_PROFILE, REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) else 'reviewed-decoder-TRAIN-resume-source-epoch-migration-failure/v1', 'error_type': type(error).__name__, 'partial_output_preserved': True, 'old_artifacts_rewritten': False, 'qualified': False, 'promotion_performed': False}))
            except BaseException as publication_error:
                error.add_note('failed to retain migration failure metadata: ' + type(publication_error).__name__)
        raise
    finally:
        if not succeeded:
            torch.set_rng_state(entry_rng)

def _reviewed_digest_cache_epoch_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current):
    """Existing paired transfer with exact equality, new proof, no numeric updates."""
    return _reviewed_epoch_family_restore(backend, model_raw, optimizer_raw, context, registry, current_admission_provider, current, _family=context['profile'])

def _reviewed_digest_cache_epoch_validate_receipt(reference, backend, *, expected_spec=None):
    """Recompute every proof and actual old/current pair; no receipt-only waiver."""
    marker=_reviewed_digest_cache_epoch_validate_marker(_thaw(backend.cache_source_epoch_marker))
    return _reviewed_epoch_family_validate_receipt(reference, backend, expected_spec=expected_spec, _family=marker['profile'])

def migrate_local_reviewed_decoder_digest_cache_source_epoch_v1(spec, *, registry, current_admission_provider, execution_guard, asset_policy_guard, recipe_artifact, model_config_artifact, tokenizer_artifact, license_artifact, old_configuration_artifact, old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact, output_directory, max_model_bytes, runtime_profile='builtin-qwen2-bfloat16/v1'):
    """Artifact-only same-digest TRAIN3 migration; explicit validated reload required; no live runtime or authority grant."""
    return _migrate_local_reviewed_decoder_epoch_family(spec, registry=registry, current_admission_provider=current_admission_provider, execution_guard=execution_guard, asset_policy_guard=asset_policy_guard, recipe_artifact=recipe_artifact, model_config_artifact=model_config_artifact, tokenizer_artifact=tokenizer_artifact, license_artifact=license_artifact, old_configuration_artifact=old_configuration_artifact, old_tokenizer_pipeline_artifact=old_tokenizer_pipeline_artifact, current_configuration_artifact=current_configuration_artifact, compatibility_contract_artifact=compatibility_contract_artifact, output_directory=output_directory, max_model_bytes=max_model_bytes, runtime_profile=runtime_profile, _family=REVIEWED_DIGEST_CACHE_EPOCH_PROFILE)
__all__ += ['ReviewedDigestCacheEpochTrainingJobSpec','REVIEWED_DIGEST_CACHE_EPOCH_JOB_SCHEMA','REVIEWED_DIGEST_CACHE_EPOCH_PROFILE','REVIEWED_DIGEST_CACHE_EPOCH_CONTRACT_SCHEMA','REVIEWED_DIGEST_CACHE_EPOCH_RECEIPT_SCHEMA','REVIEWED_DIGEST_CACHE_EPOCH_CHECKPOINT_SCHEMA','migrate_local_reviewed_decoder_digest_cache_source_epoch_v1']


def _reviewed_digest_cache_pristine_origin(origin, prospective, stage_sha256):
    """A zero-update origin has no historical training population or parent.

    The separately committed T3 receipt is prospective input equivalence DATA;
    it never asserts that this pristine numerical pair performed those updates.
    """
    need=_reviewed_epoch_need
    progress=origin.get('progress') if type(origin)is dict else None
    need(type(progress)is dict and progress=={'epochs_completed':0,'row_cursor':0,'optimizer_steps':0}
        and all(type(value)is int for value in progress.values())
        and origin.get('training_binding')is None and origin.get('parent_checkpoint_sha256')is None,
        'pristine cache origin requires exact zero progress and no historical population/parent')
    need(type(prospective)is dict
        and prospective.get('schema')=='reviewed-decoder-digest-omitted-training-input-receipt/v1'
        and prospective.get('target_codec')==REVIEWED_DIGEST_OMITTED_TARGET_CODEC
        and type(prospective.get('record_count'))is int and prospective['record_count']==3
        and prospective.get('stage_artifact_sha256')==stage_sha256,
        'separate same-objective prospective T3 input binding required')


def _reviewed_digest_cache_pristine_epoch_context(spec, old_configuration_artifact,
        old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact):
    return _reviewed_digest_cache_epoch_context(spec,old_configuration_artifact,
        old_tokenizer_pipeline_artifact,current_configuration_artifact,compatibility_contract_artifact,
        _origin_kind='pristine0')


def _reviewed_digest_cache_epoch_context_for_profile(profile):
    if profile==REVIEWED_DIGEST_CACHE_EPOCH_PROFILE:
        return _reviewed_digest_cache_epoch_context
    if profile==REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE:
        return _reviewed_digest_cache_pristine_epoch_context
    raise TrainingJobValidationError('closed same-digest TRAIN3 or PRISTINE0 cache profile required')


def migrate_local_reviewed_decoder_digest_cache_pristine_source_epoch_v1(spec, *, registry,
        current_admission_provider, execution_guard, asset_policy_guard, recipe_artifact,
        model_config_artifact, tokenizer_artifact, license_artifact, old_configuration_artifact,
        old_tokenizer_pipeline_artifact, current_configuration_artifact, compatibility_contract_artifact,
        output_directory, max_model_bytes, runtime_profile='builtin-qwen2-bfloat16/v1'):
    """Explicit pristine0 artifact migration; zero updates; validated reload required."""
    return _migrate_local_reviewed_decoder_epoch_family(spec,registry=registry,
        current_admission_provider=current_admission_provider,execution_guard=execution_guard,
        asset_policy_guard=asset_policy_guard,recipe_artifact=recipe_artifact,
        model_config_artifact=model_config_artifact,tokenizer_artifact=tokenizer_artifact,
        license_artifact=license_artifact,old_configuration_artifact=old_configuration_artifact,
        old_tokenizer_pipeline_artifact=old_tokenizer_pipeline_artifact,
        current_configuration_artifact=current_configuration_artifact,
        compatibility_contract_artifact=compatibility_contract_artifact,output_directory=output_directory,
        max_model_bytes=max_model_bytes,runtime_profile=runtime_profile,
        _family=REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE)


__all__ += ['REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE',
    'migrate_local_reviewed_decoder_digest_cache_pristine_source_epoch_v1']



def _reviewed_digest_cache_current_dependency_metadata(snapshot, old_manifest,
        old_config_sha, old_pipeline_sha, contract):
    """Explicit present-cohort DATA; never a reconstructed past observation."""
    need=_reviewed_epoch_need
    fields={'schema','profile','old_checkpoint_manifest_sha256','old_configuration_sha256',
        'current_configuration_sha256','old_tokenizer_pipeline_sha256','old_source_sha256',
        'current_source_sha256','old_source_artifacts','current_source_artifacts',
        'dependency_snapshot_artifact','old_training_binding_artifact','dependency_association_scope'}
    need(type(contract)is dict and set(contract)==fields
        and contract['schema']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA
        and contract['profile']in(REVIEWED_DIGEST_CACHE_EPOCH_PROFILE,REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE)
        and contract['dependency_association_scope']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE,
        'explicit closed digest current-cohort compatibility contract required')
    need(type(old_manifest)is dict and old_manifest.get('schema')==REVIEWED_DIGEST_OMITTED_CHECKPOINT_SCHEMA
        and old_manifest.get('backend_identity',{}).get('target_codec')==REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
        'current-cohort scope is exclusive to the same digest objective')
    source_fields=REVIEWED_DECODER_SOURCE_NAMES
    old_source,current_source=contract['old_source_sha256'],contract['current_source_sha256']
    need(type(old_source)is type(current_source)is dict and set(old_source)==set(current_source)==source_fields
        and all(type(value)is str and re.fullmatch('[0-9a-f]{64}',value)is not None
            for mapping in(old_source,current_source)for value in mapping.values())
        and old_source==old_manifest['producer_pins']
        and contract['old_checkpoint_manifest_sha256']==old_manifest['artifact_sha256']
        and contract['old_configuration_sha256']==old_config_sha
        and contract['old_tokenizer_pipeline_sha256']==old_pipeline_sha,
        'current-cohort contract old/current source and saved pair commitments differ')
    fields={'schema','association_scope','old_checkpoint_manifest_sha256','old_configuration_sha256',
        'old_tokenizer_pipeline_sha256','old_source_sha256','current_source_sha256','implementation'}
    need(type(snapshot)is dict and set(snapshot)==fields
        and snapshot['schema']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SNAPSHOT_SCHEMA
        and snapshot['association_scope']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE
        and snapshot['old_checkpoint_manifest_sha256']==old_manifest['artifact_sha256']
        and snapshot['old_configuration_sha256']==old_config_sha
        and snapshot['old_tokenizer_pipeline_sha256']==old_pipeline_sha
        and snapshot['old_source_sha256']==old_source and snapshot['current_source_sha256']==current_source,
        'current-at-migration cohort does not bind exact old pair and current Source5')


def _reviewed_epoch_family_dependencies(context, backend, *, _family):
    contract=context['contract'];spec=context['spec']
    if _family in(REVIEWED_DIGEST_CACHE_EPOCH_PROFILE,REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) and contract.get('schema')==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA:
        _reviewed_epoch_need(context['profile']==_family,'current cohort digest family differs')
        return _reviewed_epoch_dependencies(contract['dependency_snapshot_artifact'],
            {**context['old_manifest'],'artifact_sha256':spec.parent_checkpoint_artifact.sha256},
            contract['old_configuration_sha256'],contract['old_tokenizer_pipeline_sha256'],backend,
            _current_cache_contract=contract)
    _reviewed_epoch_need(_family in(REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE,
        REVIEWED_DIGEST_CACHE_EPOCH_PROFILE,REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE),
        'closed existing dependency-reader family required')
    return _reviewed_epoch_dependencies(contract['dependency_snapshot_artifact'],
        {**context['old_manifest'],'artifact_sha256':spec.parent_checkpoint_artifact.sha256},
        contract['old_configuration_sha256'],contract['old_tokenizer_pipeline_sha256'],backend)


def _reviewed_epoch_family_dependency_scope(context, *, _family):
    if _family in(REVIEWED_DIGEST_CACHE_EPOCH_PROFILE,REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE) and context['contract'].get('schema')==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA:
        _reviewed_epoch_need(context['profile']==_family
            and context['contract']['dependency_association_scope']==REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE,
            'authenticated current cohort scope differs')
        return REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE
    _reviewed_epoch_need(_family in(REVIEWED_DECODER_TRAIN_RESUME_EPOCH_PROFILE,
        REVIEWED_DIGEST_CACHE_EPOCH_PROFILE,REVIEWED_DIGEST_CACHE_PRISTINE_EPOCH_PROFILE),
        'closed existing dependency scope family required')
    return 'declared_current_cohort_before_after_Source_transition_not_historical_execution_attestation'


__all__ += ['REVIEWED_DIGEST_CACHE_CURRENT_COHORT_CONTRACT_SCHEMA',
    'REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SNAPSHOT_SCHEMA','REVIEWED_DIGEST_CACHE_CURRENT_COHORT_SCOPE']

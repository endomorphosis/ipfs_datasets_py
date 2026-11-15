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
REVIEWED_MIXED_ADMISSION_PROFILE = "complete-reviewed-mixed-sort-norm-admission/v3"
REVIEWED_MIXED_DECODER_RECEIPT_SCHEMA = "reviewed-mixed-legal-ir-decoder-worker-receipt/v1"
REVIEWED_DECODER_CHECKPOINT_SCHEMA = "reviewed-legal-ir-decoder-checkpoint/v1"
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
        expected_schema = (REVIEWED_MIXED_DECODER_SCHEMA_VERSION
            if type(self) is ReviewedMixedDecoderTrainingJobSpec else REVIEWED_DECODER_SCHEMA_VERSION)
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
                identity["target_codec"] != "complete-reviewed-norm-json/v2" or identity["source_conditioned"] is not True or
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
        expected_schema = (REVIEWED_MIXED_DECODER_SCHEMA_VERSION
            if cls is ReviewedMixedDecoderTrainingJobSpec else REVIEWED_DECODER_SCHEMA_VERSION)
        if data.get("schema_version") != expected_schema:
            raise TrainingJobValidationError("explicit reviewed decoder schema required")
        if cls is ReviewedMixedDecoderTrainingJobSpec and data.get("admission_profile") != REVIEWED_MIXED_ADMISSION_PROFILE:
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

    def __post_init__(self) -> None:
        if self.admission_profile != REVIEWED_MIXED_ADMISSION_PROFILE:
            raise TrainingJobValidationError("explicit mixed-sort admission V3 profile required")
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
    prepared = None
    mixed = type(spec) is ReviewedMixedDecoderTrainingJobSpec
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
        nonlocal prepared
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
        for item in assets:
            _reviewed_decoder_artifact(item, limit=MAX_CHECKPOINT_BYTES, load=False)
        if (_reviewed_decoder_artifact(spec.exposure_artifact) != exposure_raw or
                _reviewed_decoder_artifact(spec.source_contexts_artifact) != contexts_raw):
            raise TrainingJobValidationError("reviewed decoder context/exposure changed")
        admission = runtime.current_admission_provider()
        guard_calls["current_admission"] += 1
        try:
            prepare = (inputs.prepare_reviewed_mixed_decoder_training_inputs_v4 if mixed
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
        if (not (mixed_components if mixed else single_component or signed_components)
                or receipt.get("target_codec") != inputs.REVIEWED_DECODER_TARGET_CODEC
                or receipt.get("source_profile") != inputs.REVIEWED_DECODER_SOURCE_PROFILE
                or receipt.get("semantic_selection_supported") is not False):
            raise TrainingJobValidationError("explicit caller-known selection-context training inputs required")
        if prepared is None:
            prepared = value
        elif _json_bytes(value) != _json_bytes(prepared):
            raise TrainingJobValidationError("current reviewed decoder inputs changed before publication")
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
    model_raw = _reviewed_decoder_artifact(spec.base_model_checkpoint)
    optimizer_raw = _reviewed_decoder_artifact(spec.base_optimizer_checkpoint)
    parent = None
    progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    if spec.parent_checkpoint_artifact is not None:
        parent = _parse_json(_reviewed_decoder_artifact(spec.parent_checkpoint_artifact))
        expected_fields = {"schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
            "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
            "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed"}
        if type(parent) is not dict or set(parent) != expected_fields or parent["schema"] != REVIEWED_DECODER_CHECKPOINT_SCHEMA:
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
            progress["optimizer_steps"] != progress["epochs_completed"] * math.ceil(len(records) / spec.batch_size) +
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
            if type(report) is not dict or set(report) - {"loss", "gradient_norm", "optimizer_steps",
                    "trainable_parameter_count", "gradient_parameter_count"}:
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
                type(snapshot[key]) is not bytes or not 0 < len(snapshot[key]) <= MAX_REVIEWED_DECODER_STATE_BYTES
                for key in snapshot):
            raise TrainingJobValidationError("bounded actual model and optimizer checkpoint bytes required")
        snapshot_info = runtime.backend.inspect_checkpoint(snapshot["model_state"], snapshot["optimizer_state"])
        if snapshot_info != {"optimizer_steps": progress["optimizer_steps"]} or type(snapshot_info.get("optimizer_steps")) is not int:
            raise TrainingJobValidationError("exported backend optimizer step differs")
        current()
        if (_reviewed_decoder_artifact(spec.base_model_checkpoint) != model_raw or
                _reviewed_decoder_artifact(spec.base_optimizer_checkpoint) != optimizer_raw):
            raise TrainingJobValidationError("base model/optimizer checkpoint changed during update")
        if spec.parent_checkpoint_artifact is not None:
            _reviewed_decoder_artifact(spec.parent_checkpoint_artifact)
        model = _write_exclusive(output / "model.checkpoint", snapshot["model_state"])
        optimizer = _write_exclusive(output / "optimizer.checkpoint", snapshot["optimizer_state"])
        for item in (model, optimizer):
            _reviewed_decoder_artifact(CheckpointArtifact.from_dict(item))
        checkpoint = {"schema": REVIEWED_DECODER_CHECKPOINT_SCHEMA, "checkpoint_lineage_id": spec.checkpoint_lineage_id,
            "base_version_id": spec.base_version_id, "backend_identity": identity,
            "assets": [asdict(item) for item in assets], "training_binding": data["receipt"],
            "model_state": model, "optimizer_state": optimizer, "progress": progress,
            "batch_size": spec.batch_size, "seed": spec.seed,
            "token_budgets": {"max_source_tokens": spec.max_source_tokens, "max_target_tokens": spec.max_target_tokens,
                "tokenizer_contract": data["receipt"]["tokenizer_contract"]},
            "parent_checkpoint_sha256": spec.parent_checkpoint_artifact.sha256 if spec.parent_checkpoint_artifact else None,
            "producer_pins": source_pins, "qualified": False, "promotion_performed": False}
        current()
        checkpoint_ref = _write_exclusive(output / "reviewed-decoder-checkpoint.json", _json_bytes(checkpoint))
        _reviewed_decoder_artifact(CheckpointArtifact.from_dict(checkpoint_ref))
        current()
        receipt = {"schema_version": (REVIEWED_MIXED_DECODER_RECEIPT_SCHEMA if mixed else REVIEWED_DECODER_RECEIPT_SCHEMA),
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
    if type(spec) in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec):
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
    if type(spec) in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec):
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
    if not isinstance(spec, TrainingJobSpec) and type(spec) not in (ReviewedDecoderTrainingJobSpec, ReviewedMixedDecoderTrainingJobSpec):
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


def _reviewed_builtin_llama_rotary_buffers(model, *, initialize=False, _family="llama"):
    """Reconstruct only the built-in default RoPE's two float32 buffers.

    These deterministic values are absent from checkpoints and destroyed by
    to_empty. BF16 applies to parameters, never to this position recipe. Unknown
    registration, scaling or mutable/dynamic RoPE profiles remain unsupported.
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
    if _family == "qwen2" and (config.use_sliding_window is not False or
            config.layer_types != ["full_attention"] * config.num_hidden_layers):
        raise TrainingJobValidationError("fixed full-attention Qwen2 rotary recipe required")
    rope = config.rope_parameters
    if (type(dim) is not int or not 2 <= dim <= 65536 or dim % 2 or
            type(positions) is not int or not 1 <= positions <= 65536 or
            type(rope) is not dict or set(rope) != {"rope_type", "rope_theta"} or
            rope["rope_type"] != "default" or type(rope["rope_theta"]) not in (int, float) or
            not math.isfinite(rope["rope_theta"]) or rope["rope_theta"] <= 0):
        raise TrainingJobValidationError("fixed finite default Llama rotary recipe required")
    with torch.random.fork_rng(devices=[]):
        with torch.device("meta"):
            reference = LlamaRotaryEmbedding(config)
    expected = {"inv_freq", "original_inv_freq"}
    if (set(reference._non_persistent_buffers_set) != expected or
            set(reference._buffers) != expected or reference.attention_scaling != 1.0):
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
        if registered != (expected if module_name == "model.rotary_emb" else set()):
            raise TrainingJobValidationError("unknown or missing Llama nonpersistent buffers")
        for name in sorted(registered):
            value, witness = module._buffers.get(name), reference._buffers[name]
            if (not torch.is_tensor(value) or tuple(value.shape) != (dim // 2,) or
                    value.dtype != torch.float32 or value.device.type not in {"meta", "cpu", "cuda"} or
                    tuple(witness.shape) != (dim // 2,) or witness.dtype != torch.float32 or witness.device.type != "meta"):
                raise TrainingJobValidationError("built-in Llama rotary buffer schema differs")
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
    if value is not None and (type(value) is not str or value not in _REVIEWED_QWEN2_CHATML_PROFILES
            or architecture != "causal_lm" or model_profile != "builtin-qwen2-bfloat16/v1"):
        raise TrainingJobValidationError("explicit supported Qwen2 causal training conditioning profile required")
    return value


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
                 max_sequence_tokens, pretrained, gradient_clip=1.0, model_profile=None, training_conditioning_profile=None):
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
        self.training_conditioning_profile = _reviewed_training_conditioning_profile(
            training_conditioning_profile, architecture, model_profile)
        self.model_profile = model_profile
        self.model, self.optimizer, self.tokenizer = model, optimizer, tokenizer
        self.architecture, self.max_sequence_tokens = architecture, max_sequence_tokens
        self.pretrained, self.gradient_clip = pretrained, float(gradient_clip)
        self._optimizer_steps = 0
        self._tokenizer_pipeline_contract_raw = None

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
        configuration = {"schema": "torch-complete-reviewed-decoder-configuration/v2",
                "architecture": self.architecture, "max_sequence_tokens": self.max_sequence_tokens,
                "gradient_clip": self.gradient_clip, "pretrained_declaration": self.pretrained,
                "source_profile": "reviewed-source-selection-context/v2",
                "target_codec": "complete-reviewed-norm-json/v2", "semantic_selection_supported": False,
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
        return {"backend_id": "torch-complete-reviewed-decoder/v2:" + signature,
                "implementation_sha256": _digest(Path(__file__).read_bytes()),
                "checkpoint_format": "torch-weights-only-complete-reviewed-state-pair/v2",
                "target_codec": "complete-reviewed-norm-json/v2", "source_conditioned": True,
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
        if type(conditioning_profile) is not str or conditioning_profile not in ({"chatml-complete-legal-ir/v1"} | _REVIEWED_QWEN2_CHATML_PROFILES):
            raise TrainingJobValidationError("explicit supported ChatML conditioning profile required")
        qwen2_chatml = conditioning_profile in _REVIEWED_QWEN2_CHATML_PROFILES
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
        if conditioning_profile == REVIEWED_QWEN2_FIELD_LAYOUTS_PROFILE:
            # Public wire layouts only; never caller schema, target values,
            # an answer prefix or permission to synthesize missing facts.
            instruction += ' Public field layouts (type notation, not answer values): argument_roles is an array of objects {"symbol":string,"roles":[string]}, never an array of strings. assumptions is an array. governing_context and source_binding have exactly the fields provided in the user source wire; interpretation_id is the supplied selection identifier. typed_expression is a complete TypedExpression@1 object: interface, schema_version, expression_id, root, signature, family, profile, content_digest, metadata, and optional range; root is a typed LogicNode with kind, symbol, arguments, binders, sort, node_id, schema_version, metadata, and optional range. definition_uses entries have definition_unit_id, defined_predicate, use_unit_id, use_occurrence_cid, target_typed_paths (nonempty string array), applicability, interpretation_id, evidence_refs. cross_references entries have from_unit_id, dependency_artifact_id, dependency_sha256, version, evidence_refs. Each evidence_refs entry has artifact_id and sha256. Copy no example answer. Do not invent dependencies, identities, symbols or missing meaning, and do not emit repeated filler. Missing required facts require an empty body and EOS. Canonical JSON uses lexicographically sorted keys and no insignificant whitespace, comments or Markdown.'
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
        for index, row in enumerate(records):
            current()
            source, target = row["source_token_ids"], row["target_token_ids"]
            if self.architecture == "encoder_decoder":
                inputs = torch.tensor([source], dtype=torch.long, device=device)
                output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                    decoder_input_ids=torch.tensor([target[:-1]], dtype=torch.long, device=device),
                    labels=torch.tensor([target[1:]], dtype=torch.long, device=device))
            elif framed is not None:
                # The open assistant role predicts the first body token.
                # Logical BOS is transport only; body and EOS are labels.
                prompt = framed[index]
                inputs = torch.tensor([prompt + target[1:]], dtype=torch.long, device=device)
                labels = torch.tensor([[-100] * len(prompt) + target[1:]], dtype=torch.long, device=device)
                output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=labels)
            else:
                # The decoder model performs its own causal one-position shift.
                # The known target BOS is a prefix; only body and EOS are labels.
                inputs = torch.tensor([source + target], dtype=torch.long, device=device)
                labels = torch.tensor([[-100] * (len(source) + 1) + target[1:]], dtype=torch.long, device=device)
                output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=labels)
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
        current()
        return result


    def generate_batch(self, records, *, max_output_tokens, execution_guard,
                       generation_profile="full-prefix/v1", conditioning_profile="raw-source-bos/v1",
                       max_generation_seconds=None, context_budget_profile=None):
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
        """
        if not callable(execution_guard):
            raise TrainingJobValidationError("caller-owned generation execution guard required")
        if type(max_output_tokens) is not int or not 2 <= max_output_tokens <= 65536:
            raise TrainingJobValidationError("finite generation budget including BOS and EOS required")
        if (type(generation_profile) is not str or generation_profile not in
                {"full-prefix/v1", "builtin-llama-dynamic-kv/v1", "builtin-qwen2-dynamic-kv/v1"}):
            raise TrainingJobValidationError("closed explicit generation profile required")
        if (type(conditioning_profile) is not str or conditioning_profile not in
                ({"raw-source-bos/v1", "chatml-complete-legal-ir/v1"} | _REVIEWED_QWEN2_CHATML_PROFILES)):
            raise TrainingJobValidationError("closed explicit conditioning profile required")
        if context_budget_profile is not None and (type(context_budget_profile) is not str or
                context_budget_profile != REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE or
                conditioning_profile not in _REVIEWED_QWEN2_CHATML_PROFILES):
            raise TrainingJobValidationError("explicit matching Qwen2 context budget profile required")
        context_token_limit = (REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if context_budget_profile is not None
                               else REVIEWED_GENERATION_CONTEXT_MAX_TOKENS)
        if max_generation_seconds is not None:
            try:
                valid_duration = (type(max_generation_seconds) in (int, float)
                    and math.isfinite(max_generation_seconds))
            except OverflowError:
                valid_duration = False
            if not valid_duration or max_generation_seconds <= 0:
                raise TrainingJobValidationError("finite positive per-row generation time budget required")
        qwen2_chatml = conditioning_profile in _REVIEWED_QWEN2_CHATML_PROFILES
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

        # A direct low-level caller must not combine the new DATA transport
        # with a larger context profile. Check detached bounded records before
        # importing Torch or touching model/optimizer state. Existing v2 Qwen
        # transport remains eligible under its separate explicit contract.
        if context_budget_profile is not None:
            for row in owned:
                try:
                    source = _parse_json(row["source_wire"].encode("utf-8"))
                except (ValueError, UnicodeError) as error:
                    raise TrainingJobValidationError("canonical source-only generation JSON required") from error
                if (type(source) is dict
                        and source.get("profile") == REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3):
                    raise TrainingJobValidationError("key-layout DATA requires the unchanged default context budget")
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
        llama_buffers = tuple((value, value.detach().clone()) for _, value in model_owner.named_buffers()) if projected_model else ()
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
                    tuple(id(module) for module in model_owner.modules()),
                    tuple(tuple(id(value) for value in group["params"])
                          for group in optimizer_owner.param_groups))
        original_owner_identity = owner_identity()
        try:
            configuration = self._configuration()
            contract = configuration["tokenizer"]
            vocab, bos, eos = (contract[key] for key in ("vocab_size", "bos_token_id", "eos_token_id"))
            query_identifiers = {row[key] for row in owned for key in ("id", "unit_id")}
            input_offset = 1 if chatml else 0
            framed_sources = {}
            if cached_llama:
                from transformers.cache_utils import DynamicCache, DynamicLayer
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
                        cache = DynamicCache(config=model_owner.config)
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
                        token = int(logits[0, -1].argmax().item())
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
                and all(parameter.grad is original and parameter.requires_grad is requires_grad
                        and (original is None or self._same(original, saved))
                        for parameter, original, saved, requires_grad in gradients)
                and all(module.training is training for module, training in modes)
                and self._same(torch.get_rng_state(), cpu_rng)
                and (device_rng is None or self._same(torch.cuda.get_rng_state(device), device_rng)))
            if not restored or owner_identity() != original_owner_identity:
                raise TrainingJobValidationError("generation numeric state did not restore exactly")


__all__ += ["ReviewedPretrainedTokenizer", "TorchReviewedDecoderBackend"]


def _reviewed_decoder_generation_policy(value):
    """Closed opt-in inference DATA, never execution or legal-use authority."""
    fields = {"schema", "generation_profile", "conditioning_profile", "max_generation_seconds"}
    qwen2 = type(value) is dict and value.get("schema") == "reviewed-decoder-generation-policy/v2"
    if qwen2:
        fields.add("context_budget_profile")
    if (type(value) is not dict or set(value) != fields or
            value["schema"] != ("reviewed-decoder-generation-policy/v2" if qwen2 else "reviewed-decoder-generation-policy/v1") or
            type(value["generation_profile"]) is not str or value["generation_profile"] != ("builtin-qwen2-dynamic-kv/v1" if qwen2 else "builtin-llama-dynamic-kv/v1") or
            type(value["conditioning_profile"]) is not str or value["conditioning_profile"] not in (_REVIEWED_QWEN2_CHATML_PROFILES if qwen2 else {"chatml-complete-legal-ir/v1"}) or
            qwen2 and (type(value["context_budget_profile"]) is not str or value["context_budget_profile"] != REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE)):
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
        context_policy_guard=None, context_transport="plain_json_v1", generation_policy=None, _admission_version):
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
    generation_copy = None if generation_policy is None else _reviewed_decoder_generation_policy(generation_policy)
    qwen2_generation = generation_copy is not None and generation_copy["schema"] == "reviewed-decoder-generation-policy/v2"
    context_token_limit = REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if qwen2_generation else REVIEWED_GENERATION_CONTEXT_MAX_TOKENS
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
        and identity_copy["target_codec"] == "complete-reviewed-norm-json/v2"
        and identity_copy["source_conditioned"] is True and type(identity_copy["pretrained"]) is bool,
        "complete source-conditioned decoder identity required")
    operation = "heldout_evaluation" if allow_heldout_evaluation else "hparam_selection"
    context_enabled = context_profile is not None
    need(type(context_transport) is str and context_transport in {"plain_json_v1", "shared_json_v1", "shared_json_v2", "shared_json_v3"},
         "explicit supported admitted context transport required")
    shared_context = context_transport in {"shared_json_v1", "shared_json_v2", "shared_json_v3"}
    need(not qwen2_generation or context_profile is None or context_transport == "shared_json_v2",
         "Qwen2 reviewed rich context requires explicit lossless shared_json_v2 transport")
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
                context_budget_profile=REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE)
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
        input_profile_id=("reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2_generation
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
                    **({"context_budget_profile": REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE} if qwen2_generation else {}))
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
        expected_admission_inputs_sha256, max_model_bytes, _admission_version, _runtime_profile):
    """Load an explicitly profiled built-in CPU decoder and paired state.

    The caller owns live execution, license/asset policy and current admission.
    Verified license bytes are not permission. This loader downloads nothing,
    imports no caller-selected code, trains nothing and grants no resources.
    Model storage is bounded on meta tensors before CPU materialization. Success
    keeps the checkpoint's RNG; failure restores the CPU RNG seen at Torch entry.
    """
    import stat
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
            or identity["target_codec"] != "complete-reviewed-norm-json/v2"
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
    if llama_profile:
        recipe_fields.add("parameter_dtype")
    training_recipe = qwen2_profile and type(recipe) is dict and recipe.get("schema") == "reviewed-local-decoder-recipe/v3"
    if training_recipe:
        recipe_fields.add("training_conditioning_profile")
    if (type(recipe) is not dict or set(recipe) != recipe_fields
            or recipe["schema"] != ("reviewed-local-decoder-recipe/v3" if training_recipe else "reviewed-local-decoder-recipe/v2" if llama_profile else "reviewed-local-decoder-recipe/v1")
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
    if training_recipe and (type(recipe["training_conditioning_profile"]) is not str or recipe["training_conditioning_profile"] not in _REVIEWED_QWEN2_CHATML_PROFILES):
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
            rope = config.rope_parameters
            if (width % heads or heads % kv_heads or head_dim != width // heads or head_dim % 2 or
                    (config.use_sliding_window is not False or config.layer_types != ["full_attention"]*layers if qwen2_profile
                     else config.attention_bias is not False or config.mlp_bias is not False) or
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
                    value = model.model.rotary_emb._buffers.get(name)
                    if not torch.is_tensor(value):
                        raise TrainingJobValidationError("known Llama rotary buffers required on meta")
                    model.model.rotary_emb._buffers[name] = value.float()
            else:
                model.float()
        rotary_buffers = _reviewed_builtin_qwen2_rotary_buffers if qwen2_profile else _reviewed_builtin_llama_rotary_buffers
        causal_buffer_names = (rotary_buffers(model) if llama_profile else
            _reviewed_builtin_gpt2_causal_buffers(model) if recipe["model_type"] == "gpt2" else [])
        state_names = set(model.state_dict())
        if (any(name not in state_names and name not in causal_buffer_names for name, _ in model.named_buffers())
                or recipe["model_type"] not in {"gpt2", "llama", "qwen2"} and any(module._non_persistent_buffers_set for module in model.modules())):
            raise TrainingJobValidationError("local decoder nonpersistent buffers cannot be restored from paired checkpoint")
        tensors = {id(value): value for value in (*model.parameters(), *model.buffers())}
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
        cpu_tensors = {id(value): value for value in (*model.parameters(), *model.buffers())}
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
            **({"training_conditioning_profile": recipe["training_conditioning_profile"]} if training_recipe else {}))
        if backend.identity() != identity:
            raise TrainingJobValidationError("local constructed decoder backend identity differs")
        current()
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
            "reconstructed_deterministic_nonpersistent_buffers": causal_buffer_names,
            "tokenizer_constructor_option_order": ["bos_token", "eos_token", "unk_token", "pad_token",
                "model_max_length", "clean_up_tokenization_spaces"]}
        current()
        if backend.identity() != identity or not backend.restored_checkpoint_matches(model_raw, optimizer_raw):
            raise TrainingJobValidationError("loaded decoder pair changed after final policy guard")
        receipt["guard_calls"] = dict(guards)
        if llama_profile:
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

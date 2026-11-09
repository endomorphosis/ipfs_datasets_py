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
from dataclasses import asdict, dataclass, fields
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
        if self.schema_version != REVIEWED_DECODER_SCHEMA_VERSION:
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
        if data.get("schema_version") != REVIEWED_DECODER_SCHEMA_VERSION:
            raise TrainingJobValidationError("explicit reviewed decoder schema required")
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


def _reviewed_decoder_source_pins() -> dict[str, str]:
    from ...logic.autoformal import training_cycle_inputs, legal_norm_content_adjudication_v1
    from . import legal_span_consumer_binding, legal_ir_eval_splits
    modules = {"worker": Path(__file__), "inputs": Path(training_cycle_inputs.__file__),
        "consumer": Path(legal_span_consumer_binding.__file__), "admission": Path(legal_norm_content_adjudication_v1.__file__),
        "splits": Path(legal_ir_eval_splits.__file__)}
    return {name: _digest(path.read_bytes()) for name, path in modules.items()}


def _reviewed_decoder_artifact(reference: CheckpointArtifact, *, limit: int = MAX_REVIEWED_DECODER_STATE_BYTES,
                               load: bool = True) -> bytes | None:
    """Authenticate ordinary immutable inputs without materializing large assets."""
    import stat
    path = Path(reference.path)
    if not path.is_absolute() or path.resolve(strict=True) != path or reference.bytes > limit:
        raise TrainingJobValidationError("reviewed decoder artifact path/byte bound differs")
    for directory in path.parents:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise TrainingJobValidationError("reviewed decoder artifact ancestry is not ordinary")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        first = os.fstat(descriptor)
        if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or first.st_size != reference.bytes:
            raise TrainingJobValidationError("reviewed decoder artifact identity differs")
        digest, total, pieces = hashlib.sha256(), 0, []
        while part := os.read(descriptor, 1024**2):
            total += len(part)
            if total > reference.bytes:
                raise TrainingJobValidationError("reviewed decoder artifact grew")
            digest.update(part)
            if load:
                pieces.append(part)
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (total != reference.bytes or digest.hexdigest() != reference.sha256 or
                stamp(first) != stamp(os.fstat(descriptor)) or stamp(first) != stamp(path.lstat())):
            raise TrainingJobValidationError("reviewed decoder artifact changed")
        return b"".join(pieces) if load else None
    finally:
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
        if _reviewed_decoder_source_pins() != source_pins:
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
            value = inputs.prepare_reviewed_decoder_training_inputs(runtime.registry,
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
        if (value.get("schema") != "reviewed-decoder-training-inputs/v2" or
                value.get("receipt", {}).get("profile") != "complete-reviewed-decoder-training-inputs/v2" or
                value["receipt"].get("target_codec") != "complete-reviewed-norm-json/v2" or
                value["receipt"].get("source_profile") != "reviewed-source-selection-context/v2" or
                value["receipt"].get("semantic_selection_supported") is not False):
            raise TrainingJobValidationError("explicit caller-known selection-context v2 training inputs required")
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
        receipt = {"schema_version": REVIEWED_DECODER_RECEIPT_SCHEMA, "job_id": spec.job_id, "run_id": spec.run_id,
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
    if type(spec) is ReviewedDecoderTrainingJobSpec:
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
    if type(spec) is ReviewedDecoderTrainingJobSpec:
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
    if not isinstance(spec, TrainingJobSpec) and type(spec) is not ReviewedDecoderTrainingJobSpec:
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


__all__ = ["ReviewedDecoderTrainingJobSpec", "ReviewedDecoderRuntime", "REVIEWED_DECODER_SCHEMA_VERSION", "BRIDGE_NAMES", "CheckpointArtifact", "ModelVariant", "SampleRecord", "TrainingConfig",
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
        identity.update(code_sha256=_digest(marshal.dumps(code)),
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
                 max_sequence_tokens, pretrained, gradient_clip=1.0):
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
        self.model, self.optimizer, self.tokenizer = model, optimizer, tokenizer
        self.architecture, self.max_sequence_tokens = architecture, max_sequence_tokens
        self.pretrained, self.gradient_clip = pretrained, float(gradient_clip)
        self._optimizer_steps = 0
        self._tokenizer_pipeline_contract_raw = None

    def _torch(self):
        import torch
        return torch

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
                if total > MAX_REVIEWED_DECODER_STATE_BYTES or not bool(torch.isfinite(item).all()):
                    raise TrainingJobValidationError("nonfinite or oversized Torch checkpoint tensors")
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
            if used > self.max_sequence_tokens:
                raise TrainingJobValidationError("full source and target exceed actual decoder context; truncation forbidden")
        # Merely validating representability does not construct a model or fit.
        if not callable(getattr(torch, "save", None)) or not callable(getattr(torch, "load", None)):
            raise TrainingJobValidationError("Torch checkpoint support unavailable")
        self._assert_pipeline(config["tokenizer"])

    def _load_pair(self, model_bytes, optimizer_bytes):
        import io
        torch = self._torch()
        for raw in (model_bytes, optimizer_bytes):
            if type(raw) is not bytes or not 0 < len(raw) <= MAX_REVIEWED_DECODER_STATE_BYTES:
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

    def restore_checkpoint(self, model_bytes, optimizer_bytes):
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
        if not self.restored_checkpoint_matches(model_bytes, optimizer_bytes):
            raise TrainingJobValidationError("Torch model/optimizer state did not restore exactly")

    def _same(self, left, right):
        torch = self._torch()
        if torch.is_tensor(left) or torch.is_tensor(right):
            return (torch.is_tensor(left) and torch.is_tensor(right) and left.dtype == right.dtype and
                    tuple(left.shape) == tuple(right.shape) and torch.equal(left.detach().cpu(), right.detach().cpu()))
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
            if not 0 < len(raw) <= MAX_REVIEWED_DECODER_STATE_BYTES:
                raise TrainingJobValidationError("Torch checkpoint exceeds declared state byte limit")
            result[name] = raw
            self._assert_pipeline(contract)
        return result

    def train_batch(self, records):
        if type(self._optimizer_steps) is not int or not 0 <= self._optimizer_steps < 10**9:
            raise TrainingJobValidationError("Torch optimizer progress capacity exhausted before update")
        torch = self._torch()
        self.validate_training_records(records, max_source_tokens=self.max_sequence_tokens,
                                       max_target_tokens=self.max_sequence_tokens)
        contract = self._pipeline_contract()
        device = next(self.model.parameters()).device
        self.model.train()
        self._assert_pipeline(contract)
        self.optimizer.zero_grad(set_to_none=True)
        self._assert_pipeline(contract)
        losses = []
        for row in records:
            self._assert_pipeline(contract)
            source, target = row["source_token_ids"], row["target_token_ids"]
            if self.architecture == "encoder_decoder":
                inputs = torch.tensor([source], dtype=torch.long, device=device)
                output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                    decoder_input_ids=torch.tensor([target[:-1]], dtype=torch.long, device=device),
                    labels=torch.tensor([target[1:]], dtype=torch.long, device=device))
            else:
                # The decoder model performs its own causal one-position shift.
                # The known target BOS is a prefix; only body and EOS are labels.
                inputs = torch.tensor([source + target], dtype=torch.long, device=device)
                labels = torch.tensor([[-100] * (len(source) + 1) + target[1:]], dtype=torch.long, device=device)
                output = self.model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=labels)
            self._assert_pipeline(contract)
            loss = getattr(output, "loss", None)
            if not torch.is_tensor(loss) or loss.ndim != 0 or not bool(torch.isfinite(loss)):
                raise TrainingJobValidationError("pretrained model must return a finite scalar teacher-forced loss")
            losses.append(loss)
        loss = torch.stack(losses).mean()
        self._assert_pipeline(contract)
        loss.backward()
        self._assert_pipeline(contract)
        parameters = [value for value in self.model.parameters() if value.requires_grad]
        gradients = [value.grad for value in parameters if value.grad is not None]
        if not gradients or any(not bool(torch.isfinite(value).all()) for value in gradients):
            raise TrainingJobValidationError("pretrained loss produced missing or nonfinite gradients")
        norm = torch.nn.utils.clip_grad_norm_(parameters, self.gradient_clip, error_if_nonfinite=True)
        self._assert_pipeline(contract)
        self.optimizer.step()
        self._optimizer_steps += 1
        self._assert_pipeline(contract)
        self._finite_state(self._model_state())
        self._finite_state(self.optimizer.state_dict())
        self._assert_pipeline(contract)
        result = {"loss": float(loss.detach().cpu()), "gradient_norm": float(norm.detach().cpu()),
                  "optimizer_steps": self._optimizer_steps,
                  "trainable_parameter_count": len(parameters), "gradient_parameter_count": len(gradients)}
        self._assert_pipeline(contract)
        return result


__all__ += ["ReviewedPretrainedTokenizer", "TorchReviewedDecoderBackend"]

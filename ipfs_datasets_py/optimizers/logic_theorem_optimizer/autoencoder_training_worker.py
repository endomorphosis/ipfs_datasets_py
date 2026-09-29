"""Independent, bounded projection jobs over immutable JSON checkpoints.

This is a worker boundary, not a scheduler or promotion authority. Each process
owns a private model. It emits an immutable candidate and evidence into a new
directory; it never opens a control database. Candidates default to full JSON;
opt-in sparse manifests reference explicitly supplied immutable dependencies.
"""

from __future__ import annotations

from .autoencoder_native_pool import worker_runtime

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

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
        for name in ("job_id", "run_id", "base_version_id", "output_directory", "code_identity",
                     "dataset_snapshot_id", "split_snapshot_id"):
            _text(getattr(self, name), name)
        _text(self.target_snapshot_id, "target_snapshot_id", empty=True)
        if bool(self.target_snapshot_id) != (self.target_snapshot_artifact is not None):
            raise TrainingJobValidationError("target snapshot ID and artifact must be supplied together")
        if self.target_snapshot_artifact is not None and not isinstance(self.target_snapshot_artifact, CheckpointArtifact):
            raise TrainingJobValidationError("target_snapshot_artifact must be CheckpointArtifact")
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
    def from_dict(cls, value: Any) -> "TrainingJobSpec":
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
             reduce_native_targets: bool = False) -> dict[str, Any]:
    global _PROCESS_SOURCE_HASHES
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
            shared_targets, target_hydration_gc, streamed_reduction = _stream_reduced_shared_targets(
                target_snapshot, members, target_config, defer_gc=defer_target_hydration_gc,
                prepare=prepare_native_targets)
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


def execute_training_job(spec: TrainingJobSpec, *,
                         trainer: Callable[..., Mapping[str, Any]] | None = None,
                         job_file_sha256: str | None = None) -> dict[str, Any]:
    """Run one private candidate job; ``trainer`` is a local test injection.

    Start concurrent jobs in independent processes. The model's existing
    optimizer owns its transactions; this adapter does not nest an outer one.
    """
    return _execute_training_job(spec, trainer=trainer, job_file_sha256=job_file_sha256)


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
                          reduce_native_targets: bool = False) -> dict[str, Any]:
    if type(reduce_native_targets) is not bool:
        raise TrainingJobValidationError("reduce_native_targets must be boolean")
    if reduce_native_targets and trainer is not None:
        raise TrainingJobValidationError("target reduction requires the native spawned worker without an injected trainer")
    if not isinstance(spec, TrainingJobSpec):
        raise TrainingJobValidationError("spec must be a TrainingJobSpec")
    if not _JOB_LOCK.acquire(blocking=False):
        raise TrainingJobValidationError("only one training job may run per worker process")
    try:
        with ExitStack() as resources, _worker_environment():
            return _execute(spec, trainer, job_file_sha256, resources,
                            defer_target_hydration_gc=defer_target_hydration_gc,
                            reduce_native_targets=reduce_native_targets)
    finally:
        _JOB_LOCK.release()


def execute_training_job_file(path: str | Path, expected_sha256: str, *,
                              trainer: Callable[..., Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Verify a job artifact and execute those same JSON bytes in this process."""
    raw = Path(path).read_bytes()
    if _digest(raw) != expected_sha256:
        raise TrainingJobValidationError("job file SHA-256 mismatch")
    spec = TrainingJobSpec.from_dict(_parse_json(raw))
    return execute_training_job(spec, trainer=trainer, job_file_sha256=expected_sha256)


__all__ = ["BRIDGE_NAMES", "CheckpointArtifact", "ModelVariant", "SampleRecord", "TrainingConfig",
           "TrainingJobSpec", "TrainingJobValidationError", "execute_training_job", "execute_training_job_file",
           "verify_corpus_job_inputs"]

"""Validation shared by the opt-in, side-by-side lineage facades.

No model state is converted between implementations. Checkpoint loading reads
existing local JSON and never saves, downloads, or replaces a checkpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import importlib
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import stat
from typing import Any


HISTORICAL_CHECKPOINTS = frozenset({
    "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be",
    "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd",
})
TEACHER_CHECKPOINT_SHA256 = "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"
SNAPSHOT_MANIFEST_SHA256 = "58935518a2114e361855f8832ab4c38af5671296fde657053e15a9139baaa314"
HASH_CHUNK_BYTES = 1024 * 1024


def verify_snapshot(directory: Path) -> dict[str, Any]:
    """Verify the small vendored source closure before importing its code."""
    raw = (directory / "MANIFEST.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_MANIFEST_SHA256:
        raise ValueError("legacy source snapshot manifest SHA256 mismatch")
    manifest = json.loads(raw)
    checks = [(directory / "__init__.py", manifest["snapshot_init_sha256"])]
    checks.extend((directory / Path(item["vendored_path"]).name,
                   item["vendored_sha256"]) for item in manifest["files"])
    for path, expected in checks:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"legacy source snapshot SHA256 mismatch: {path.name}")
    return manifest


def _package_root() -> Path:
    # Also permits a staged facade under this checkout during source validation.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "ipfs_datasets_py"
        if (candidate / "logic" / "autoformal" / "tree_pin.py").is_file():
            return candidate.resolve()
    raise RuntimeError("cannot identify this facade's canonical package tree")


def require_canonical_modules(implementation_module: str) -> dict[str, str]:
    expected = _package_root()
    pin = importlib.import_module("ipfs_datasets_py.logic.autoformal.tree_pin")
    pin_path = Path(pin.__file__).resolve()
    if expected not in pin_path.parents:
        raise RuntimeError(f"tree pin loaded outside canonical package tree: {pin_path}")
    resolved = pin.require_workspace_logic_tree()
    # Staged legacy modules are explicitly verified by their frozen manifest.
    if "._snapshot." not in implementation_module:
        module = importlib.import_module(implementation_module)
        path = Path(module.__file__).resolve()
        if expected not in path.parents:
            raise RuntimeError(f"autoencoder loaded outside canonical package tree: {path}")
    return resolved


def validate_vector(vector: Any, dimension: int, label: str) -> None:
    if isinstance(vector, (str, bytes, bytearray, Mapping)):
        raise ValueError(f"{label}: expected {dimension} numeric values")
    try:
        length = len(vector)
    except (TypeError, AttributeError) as exc:
        raise ValueError(f"{label}: expected {dimension} numeric values") from exc
    if length != dimension:
        raise ValueError(f"{label}: expected {dimension} values, got {length}")
    for number in vector:
        if isinstance(number, bool) or not isinstance(number, Real) or not math.isfinite(number):
            raise ValueError(f"{label}: values must be finite real numbers")


def validate_sample(sample: Any, dimension: int) -> None:
    validate_vector(getattr(sample, "embedding_vector", None), dimension,
                    f"sample {getattr(sample, 'sample_id', '<unknown>')} embedding_vector")


def _validate_embedding_rows(rows: Any, dimension: int, label: str) -> None:
    if not isinstance(rows, Mapping):
        raise ValueError(f"{label}: only dense row mappings are supported by this lineage facade")
    for key, row in rows.items():
        validate_vector(row, dimension, f"{label}[{key!r}]")


class LineageModelContract:
    """Boundary checks for the public facades; original core APIs stay intact.

    Samples may be duck-typed across the two historical dataclasses when their
    embedding width matches. Their IR/semantic compatibility is still checked by
    the selected implementation. A width check never verifies an encoder model.
    """

    def __init__(self, *, state=None, **kwargs):
        self._checkpoint_identity = None
        self._joint_formula_checkpoint = None
        self._joint_formula_decoder = None
        self._logic_tree = require_canonical_modules(self._implementation_class.__module__)
        if state is None:
            state = self._training_state_class()
        self._validate_state(state, scan_rows=True)
        super().__init__(state=state, **kwargs)

    def _validate_state(self, state, *, scan_rows=False):
        if type(state) is not self._training_state_class:
            expected = self._training_state_class
            raise TypeError(f"{self.LINEAGE_ID} requires {expected.__module__}.TrainingState; "
                            f"received {type(state).__module__}.{type(state).__name__}")
        if scan_rows:
            for name in state.__dataclass_fields__:
                if name != "decoded_embeddings" and not name.endswith("_embedding_weights"):
                    continue
                _validate_embedding_rows(getattr(state, name), self.DIMENSION, f"state.{name}")

    def _samples(self, samples):
        result = list(samples)
        for sample in result:
            validate_sample(sample, self.DIMENSION)
        return result

    def encode(self, sample, **kwargs):
        self._validate_state(self.state)
        validate_sample(sample, self.DIMENSION)
        if self._joint_formula_checkpoint is not None:
            if set(kwargs) - {"use_sample_memory"}:
                raise ValueError("joint formula encode accepts only use_sample_memory=False")
            if kwargs.get("use_sample_memory", False) is not False:
                raise ValueError("joint formula encode forbids sample memory")
            from ..modal_joint_formula import projected_embedding
            return {"sample_id": sample.sample_id,
                    "embedding_projection": projected_embedding(self, sample),
                    "projection_origin": "joint_learned_residual_projection",
                    "use_sample_memory": False}
        result = super().encode(sample, **kwargs)
        validate_vector(result.get("embedding_projection"), self.DIMENSION, "encoded embedding_projection")
        return result

    def decode(self, encoded):
        self._validate_state(self.state)
        if not isinstance(encoded, Mapping):
            raise ValueError("encoded input must be a mapping")
        validate_vector(encoded.get("embedding_projection"), self.DIMENSION, "encoded embedding_projection")
        result = super().decode(encoded)
        validate_vector(result, self.DIMENSION, "decoded embedding")
        return result

    def evaluate(self, samples, **kwargs):
        self._validate_state(self.state)
        if self._joint_formula_checkpoint is not None:
            if kwargs:
                raise ValueError("joint formula evaluation accepts no bridge options; it evaluates the trained projection and decoder")
            from ..modal_joint_formula import infer
            return infer(self, samples)
        sample_list = self._samples(samples)
        if self._raw_reconstruction_default:
            kwargs.setdefault("reconstruction_objective", "raw_decoder")
            kwargs.setdefault("use_sample_memory", False)
        result = super().evaluate(sample_list, **kwargs)
        for key, vector in result.decoded_embeddings.items():
            validate_vector(vector, self.DIMENSION, f"evaluation decoded_embeddings[{key!r}]")
        return result

    def train_generalizable_projection(self, samples, *, validation_samples=None,
                                      formula_targets=None, validation_formula_targets=None,
                                      formula_options=None, **kwargs):
        self._validate_state(self.state)
        if formula_targets is not None or self._joint_formula_checkpoint is not None:
            if formula_targets is None or validation_formula_targets is None or validation_samples is None:
                raise ValueError("joint training requires explicit training and validation formula targets; decoder training cannot be skipped")
            from ..modal_joint_formula import train
            return train(self, samples, formula_targets, validation_samples=validation_samples,
                         validation_targets=validation_formula_targets,
                         formula_options=formula_options, **kwargs)
        if validation_formula_targets is not None or formula_options is not None:
            raise ValueError("formula configuration requires training formula targets")
        sample_list = self._samples(samples)
        validation = None if validation_samples is None else self._samples(validation_samples)
        if self._raw_reconstruction_default:
            kwargs.setdefault("projection_reconstruction_objective", "raw_decoder")
        return super().train_generalizable_projection(
            sample_list, validation_samples=validation, **kwargs)

    def describe(self) -> dict[str, Any]:
        """Return provenance, not an admission or semantic qualification."""
        return {
            "lineage_id": self.LINEAGE_ID,
            "dimension": self.DIMENSION,
            "expected_embedding_dimension": self.DIMENSION,
            "implementation_module": self._implementation_class.__module__,
            "training_state_class": f"{self._training_state_class.__module__}.{self._training_state_class.__name__}",
            "loaded_architecture_version": self.state.architecture_version,
            "checkpoint_identity": None if self._checkpoint_identity is None else dict(self._checkpoint_identity),
            "raw_declared_architecture_version": None if self._checkpoint_identity is None else self._checkpoint_identity["raw_declared_architecture_version"],
            "checkpoint_loader_formats": ["json"],
            "implementation_scope": self._implementation_scope,
            "shared_canonical_logic_modules": dict(self._logic_tree),
            "independent_formula_decoder": False,
            "learned_latent_formula_decoder": self._joint_formula_checkpoint is not None,
            "formal_logic_decoder_modes": ["guided_compiler", "canonical_compiler"] +
                (["learned_latent"] if self._joint_formula_checkpoint is not None else []),
            "joint_formula_profile": self.formula_decoder_description(),
            "semantic_embedding_verified": False,
            "semantic_qualification": False,
            "admitted": False,
        }

    def decode_formal_logic(self, samples, *, mode=None, **options):
        """Use an attached learned head by default; keep compiler modes explicit."""
        mode = mode or ("learned_latent" if self._joint_formula_checkpoint is not None else "guided_compiler")
        if mode == "learned_latent":
            if options:
                raise ValueError("learned latent inference has no compiler or sampling options")
            from ..modal_joint_formula import infer
            return infer(self, samples)
        from ..legal_formal_decoder import decode_legal_formulas
        return decode_legal_formulas(self, samples, mode=mode, **options)

    def formula_decoder_description(self):
        from ..modal_joint_formula import describe
        return describe(self)

    @property
    def formula_checkpoint(self):
        return None if self._joint_formula_checkpoint is None else json.loads(json.dumps(self._joint_formula_checkpoint))

    def attach_formula_checkpoint(self, checkpoint):
        from ..modal_joint_formula import attach
        return attach(self, checkpoint)

    def save_formula_checkpoint(self, path):
        from ..modal_joint_formula import save
        return save(self, path)

    def load_formula_checkpoint(self, path, *, expected_sha256):
        from ..modal_joint_formula import load
        return load(self, path, expected_sha256=expected_sha256)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stable_hash(path: Path):
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("checkpoint must be an existing regular file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise ValueError("checkpoint changed before hashing")
        while chunk := handle.read(HASH_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    if size != before.st_size or _identity(before) != _identity(after) or _identity(before) != _identity(path.stat()):
        raise ValueError("checkpoint changed during hashing")
    return digest.hexdigest(), _identity(before)


def load_local_checkpoint(model_class, path, *, expected_sha256: str, **model_options):
    """Strict local JSON loader; the caller supplies the full expected hash.

    Compact containers remain available through the original checkpoint APIs;
    this convenience loader rejects them so raw architecture metadata cannot be
    silently lost. The source file is checked again after deserialization.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters")
    if "state" in model_options:
        raise TypeError("state cannot be supplied when loading a checkpoint")
    if model_class.LINEAGE_ID == "current_legal_v2" and expected_sha256 in HISTORICAL_CHECKPOINTS:
        raise ValueError("checkpoint SHA256 belongs to a forbidden historical lineage")
    source = Path(path).resolve(strict=True)
    actual, identity = _stable_hash(source)
    if actual != expected_sha256:
        raise ValueError(f"checkpoint SHA256 mismatch: expected {expected_sha256}, observed {actual}")
    with source.open("rb") as handle:
        if handle.read(8) == b"LIRMAECP":
            raise ValueError("lineage load_checkpoint supports JSON only; compact binary containers require the original checkpoint APIs")
    state_class = model_class._training_state_class
    raw_metadata = {}

    class CaptureRawArchitecture(state_class):
        @classmethod
        def from_dict(cls, data, *args, **kwargs):
            if not isinstance(data, Mapping):
                raise ValueError("checkpoint JSON must contain a state object")
            for name, rows in data.items():
                if name == "decoded_embeddings" or name.endswith("_embedding_weights"):
                    _validate_embedding_rows(rows, model_class.DIMENSION, f"checkpoint.{name}")
            raw_metadata["architecture_version"] = data.get("architecture_version")
            return state_class.from_dict(data, *args, **kwargs)

    state = CaptureRawArchitecture.load_json(source)
    actual_after, identity_after = _stable_hash(source)
    if actual_after != actual or identity_after != identity:
        raise ValueError("checkpoint changed during loading")
    model = model_class(state=state, **model_options)
    raw_architecture = raw_metadata.get("architecture_version")
    model._checkpoint_identity = {
        "path": str(source), "sha256": actual, "size_bytes": identity[2],
        "raw_declared_architecture_version": raw_architecture,
        "loaded_architecture_version": state.architecture_version,
        "compatibility_architecture_relabelled": raw_architecture != state.architecture_version,
        "exact_published_legacy_teacher": actual == TEACHER_CHECKPOINT_SHA256,
        "read_only_checkpoint_load": True,
        "lineage_ancestry_verified": False,
    }
    return model

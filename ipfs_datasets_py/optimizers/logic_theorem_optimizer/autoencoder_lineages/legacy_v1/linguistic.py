"""Preserved 8D linguistic feature reconstruction, separate from formula heads.

The historical numerical optimizer and feature-hashing codec are unchanged.
Their reconstruction objective includes a target-aware analytic projection;
its cosine/MSE is diagnostic, not independent formula fidelity or admission.
Canonical compiler/decompiler and Lake remain the shared workspace services.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.metadata
import inspect
from itertools import islice
import json
import os
from pathlib import Path
import stat
from typing import Any

from . import Autoencoder, SOURCE_REVISION, build_sample as _build_sample, _Implementation
from .._contract import SNAPSHOT_MANIFEST_SHA256, load_local_checkpoint
from ._linguistic_snapshot import MANIFEST_SHA256, verify_snapshot
from ._linguistic_snapshot.spacy_modal_codec import SpaCyLegalEncoder, SpaCyModalCodec

PROFILE_ID = "legacy-linguistic-features-8d/v1"
CHECKPOINT_SCHEMA = "legacy-linguistic-training-checkpoint/v1"
BACKENDS = ("historical_blank_en", "local_en_core_web_sm")
_HISTORICAL_MODEL_NAME = "definitely_missing_legal_model"
_MAX_CORE_BYTES = 512 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_FALSE = {"admitted": False, "formalized": False, "semantic_qualification": False,
          "independent_formula_generation": False}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, limit):
    """Read one bounded regular file, refusing links and concurrent rewrites."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError(f"invalid bounded checkpoint file: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        raw = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    if (len(raw) > limit or identity(before) != identity(opened)
            or identity(opened) != identity(after) or identity(after) != identity(path.lstat())):
        raise ValueError(f"checkpoint changed during read: {path.name}")
    return raw


class _HistoricalBlankEncoder(SpaCyLegalEncoder):
    def _load_nlp(self, model_name):
        # Reproduce the historical intentionally missing-model fallback
        # explicitly, rather than depending on whether that name is installed.
        import spacy
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        return nlp, True


def _model_package_identity(backend):
    import spacy
    identity = {"spacy_version": spacy.__version__, "language": "en"}
    if backend == "historical_blank_en":
        return {**identity, "package": None, "model_version": None,
                "model_files_sha256": None}
    package = spacy.util.get_package_path("en_core_web_sm")
    digest = hashlib.sha256()
    # Hash local installed model assets, not the mutable runtime vocabulary.
    # spaCy adds observed strings while encoding; hashing nlp.to_bytes() would
    # make an unchanged model identity depend on which documents ran first.
    for path in sorted(package.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(package).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    return {**identity, "package": "en_core_web_sm",
            "model_version": importlib.metadata.version("en_core_web_sm"),
            "model_files_sha256": digest.hexdigest()}


class LinguisticAutoencoder(Autoencoder):
    """Explicit legacy feature profile; no learned formula head may attach.

    ``historical_blank_en`` preserves the old daemon's tokenizer fallback.
    ``local_en_core_web_sm`` is a separately identified richer local feature
    configuration and fails when its installed model is unavailable.
    """

    def __init__(self, *, backend="historical_blank_en", state=None,
                 max_codec_feature_keys=64, **legacy_options):
        if backend not in BACKENDS:
            raise ValueError(f"backend must be one of {BACKENDS}")
        if type(max_codec_feature_keys) is not int or not 1 <= max_codec_feature_keys <= 4096:
            raise ValueError("max_codec_feature_keys must be an integer from 1 to 4096")
        if "feature_codec" in legacy_options:
            raise ValueError("the preserved linguistic profile owns its feature codec")
        if any(legacy_options.get(name) is not None for name in (
                "legacy_embedding_adapters", "legacy_distillation_adapters")):
            raise ValueError("external adapters are not supported by the preserved linguistic profile")
        if set(legacy_options) & {"formula_targets", "validation_formula_targets",
                                  "formula_options", "formula_checkpoint", "joint_formula_checkpoint"}:
            raise ValueError("formula options belong to the separate latent-formula profile")
        # Checkpoints retain the constructor's exact finite JSON configuration.
        options = json.loads(_bytes(legacy_options))
        verify_snapshot()
        self.backend = backend
        if backend == "historical_blank_en":
            encoder = _HistoricalBlankEncoder(model_name=_HISTORICAL_MODEL_NAME)
        else:
            encoder = SpaCyLegalEncoder(model_name="en_core_web_sm")
            if encoder.used_fallback_model:
                raise ValueError("local_en_core_web_sm requires the installed model; fallback is forbidden")
        codec = SpaCyModalCodec(encoder=encoder)
        self._linguistic_codec = codec
        self._linguistic_options = {"backend": backend,
                                    "max_codec_feature_keys": max_codec_feature_keys,
                                    **options}
        self._linguistic_identity = {
            "profile_id": PROFILE_ID, "backend": backend,
            "codec_manifest_sha256": MANIFEST_SHA256,
            "numerical_manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
            "source_revision": SOURCE_REVISION,
            "profile_source_sha256": _sha(Path(__file__).read_bytes()),
            "encoder_model_name": encoder.model_name,
            "used_fallback_model": encoder.used_fallback_model,
            "pipeline": list(encoder.nlp.pipe_names),
            "pipeline_config_sha256": _sha(encoder.nlp.config.to_str().encode()),
            **_model_package_identity(backend),
        }
        self._linguistic_identity_sha256 = _sha(_bytes(self._linguistic_identity))
        self._linguistic_embedding_model = (
            "linguistic:spacy-feature-hash8d:" + self._linguistic_identity_sha256)
        super().__init__(state=state, feature_codec=codec,
                         max_codec_feature_keys=max_codec_feature_keys, **options)
        self._linguistic_effective_configuration = self._effective_configuration()

    def _effective_configuration(self):
        # Bind even defaults: otherwise changing an attribute after construction
        # would silently save old constructor arguments and resume differently.
        values = {}
        for name in inspect.signature(_Implementation.__init__).parameters:
            if name in {"self", "state", "feature_codec", "legacy_embedding_adapters",
                        "legacy_distillation_adapters", "proof_feedback_version_fingerprint"}:
                continue
            if name == "compute_device":
                values[name] = {"request": self.compute_device_request,
                                "backend": self.compute_backend, "device": str(self.compute_device)}
            else:
                values[name] = getattr(self, name)
        # Proof feedback fingerprints belong to the serialized trainable state;
        # the optional initial constraint remains in constructor configuration.
        return json.loads(_bytes(values))

    def _require_profile(self):
        if self.feature_codec is not self._linguistic_codec:
            raise ValueError("preserved linguistic feature codec was replaced")
        if self._joint_formula_checkpoint is not None or self._joint_formula_decoder is not None:
            raise ValueError("the linguistic profile cannot contain a latent-formula head")
        if self.max_codec_feature_keys != self._linguistic_options["max_codec_feature_keys"]:
            raise ValueError("linguistic feature limit changed after construction")
        if self.backend != self._linguistic_options["backend"]:
            raise ValueError("linguistic backend changed after construction")
        if self._legacy_embedding_adapters is not None:
            raise ValueError("external adapters are forbidden in the preserved linguistic profile")
        if self._effective_configuration() != self._linguistic_effective_configuration:
            raise ValueError("linguistic effective configuration changed after construction")
        encoder = self._linguistic_codec.encoder
        if (encoder.model_name != self._linguistic_identity["encoder_model_name"]
                or encoder.used_fallback_model != self._linguistic_identity["used_fallback_model"]
                or list(encoder.nlp.pipe_names) != self._linguistic_identity["pipeline"]
                or _sha(encoder.nlp.config.to_str().encode()) != self._linguistic_identity["pipeline_config_sha256"]):
            raise ValueError("linguistic encoder configuration changed after construction")

    def _check_embedding_provenance(self, sample):
        embedding_model = getattr(sample, "embedding_model", "")
        if (isinstance(embedding_model, str)
                and embedding_model.startswith("linguistic:spacy-feature-hash8d:")
                and embedding_model != self._linguistic_embedding_model):
            raise ValueError("sample linguistic embedding belongs to another backend or codec identity")

    def _samples(self, samples):
        rows = super()._samples(samples)
        for sample in rows:
            self._check_embedding_provenance(sample)
        return rows

    def formula_decoder_description(self):
        return {"attached": False, "profile_id": PROFILE_ID,
                "allowed": False, "reason": "separate_preserved_linguistic_profile", **_FALSE}

    def describe(self):
        self._require_profile()
        return {**super().describe(), "training_profile": PROFILE_ID,
                "linguistic_identity": json.loads(_bytes(self._linguistic_identity)),
                "linguistic_identity_sha256": self._linguistic_identity_sha256,
                "linguistic_embedding_model": self._linguistic_embedding_model,
                "effective_configuration": json.loads(_bytes(self._linguistic_effective_configuration)),
                "formal_logic_decoder_modes": ["canonical_compiler"],
                "feature_codec_scope": "frozen linguistic feature hashing and modal IR; canonical compiler shared",
                "historical_daemon_feature_codec_replay": False,
                "reconstruction_objective": "historical_target_aware_safe_projection",
                "reconstruction_is_fidelity_evidence": False,
                "formula_training_executed": False, **_FALSE}

    def build_sample(self, *, title, section, text, citation=None):
        self._require_profile()
        if not isinstance(text, str) or not text.strip():
            raise ValueError("linguistic samples require nonempty source text")
        resolved_citation = citation or f"{title} U.S.C. {section}"
        encoding = self._linguistic_codec.encoder.encode(text, source="us_code", citation=resolved_citation)
        vector = self._linguistic_codec.decoder.decode_embedding(encoding, dimensions=8)
        sample = _build_sample(title=title, section=section, text=text, citation=citation,
                               embedding_vector=vector, embedding_model=self._linguistic_embedding_model)
        trace = {**sample.parser_trace, "embedding_origin": "deterministic_linguistic_feature_hash",
                 "linguistic_profile_id": PROFILE_ID,
                 "linguistic_identity_sha256": self._linguistic_identity_sha256,
                 "semantic_embedding_verified": False}
        return replace(sample, parser_trace=trace)

    def linguistic_observation(self, sample):
        self._require_profile()
        self._samples([sample])
        encoding = self._linguistic_codec.encode_sample(sample)
        ir = self._linguistic_codec.compiler.compile(encoding)
        return {"profile_id": PROFILE_ID, "backend": self.backend,
                "linguistic_identity_sha256": self._linguistic_identity_sha256,
                "source_sha256": _sha(sample.text.encode()),
                "encoding": encoding.to_dict(), "modal_ir": ir.to_dict(),
                "decoded_feature_vector": self._linguistic_codec.decoder.decode_embedding(encoding, dimensions=8),
                "feature_keys": list(self._linguistic_codec.decoder._feature_stream(encoding)),
                "vector_origin": "deterministic_linguistic_feature_hash",
                "formula_origin": "frozen_linguistic_ir_compiler", **_FALSE}

    def encode(self, sample, **kwargs):
        self._require_profile()
        self._check_embedding_provenance(sample)
        kwargs.setdefault("use_sample_memory", False)
        return super().encode(sample, **kwargs)

    def decode(self, encoded):
        self._require_profile()
        return super().decode(encoded)

    def evaluate(self, samples, **kwargs):
        self._require_profile()
        kwargs.setdefault("use_sample_memory", False)
        return super().evaluate(samples, **kwargs)

    def train_generalizable_projection(self, samples, *, validation_samples=None, **kwargs):
        self._require_profile()
        if any(name in kwargs for name in ("formula_targets", "validation_formula_targets", "formula_options")):
            raise ValueError("formula training is forbidden in the preserved linguistic profile")
        train = self._samples(samples)
        validation = [] if validation_samples is None else self._samples(validation_samples)
        if not train or not validation:
            raise ValueError("legacy linguistic training requires nonempty training and validation samples")
        train_ids = {row.sample_id for row in train}
        validation_ids = {row.sample_id for row in validation}
        normalize = lambda row: " ".join(str(row.text).lower().split())
        if (len(train_ids) != len(train) or len(validation_ids) != len(validation)
                or train_ids & validation_ids
                or {normalize(row) for row in train} & {normalize(row) for row in validation}):
            raise ValueError("legacy linguistic training requires disjoint unique validation sources")
        return super().train_generalizable_projection(train, validation_samples=validation, **kwargs)

    def decode_formal_logic(self, samples, *, mode="canonical_compiler", **options):
        self._require_profile()
        if mode != "canonical_compiler":
            raise ValueError("the linguistic profile supports only canonical_compiler; use linguistic_observation for frozen linguistic IR")
        # Preserve the common decoder's 128-row batch cap without consuming an
        # unbounded input iterator before it can enforce that boundary.
        return super().decode_formal_logic(self._samples(islice(iter(samples), 129)), mode=mode, **options)

    def attach_legacy_embedding_adapters(self, bundle):
        raise ValueError("external adapters cannot attach to the preserved linguistic profile")

    attach_legacy_distillation_adapters = attach_legacy_embedding_adapters

    def attach_formula_checkpoint(self, checkpoint):
        raise ValueError("latent-formula checkpoints cannot attach to the preserved linguistic profile")

    def load_formula_checkpoint(self, *args, **kwargs):
        raise ValueError("latent-formula checkpoints cannot load into the preserved linguistic profile")

    def save_formula_checkpoint(self, *args, **kwargs):
        raise ValueError("the preserved linguistic profile has no latent-formula checkpoint")

    def save_training_checkpoint(self, directory):
        self._require_profile()
        verify_snapshot()
        current_identity = {**self._linguistic_identity,
                            **_model_package_identity(self.backend),
                            "profile_source_sha256": _sha(Path(__file__).read_bytes())}
        if current_identity != self._linguistic_identity:
            raise ValueError("linguistic source or installed backend changed before checkpoint")
        core = _bytes(self.state.to_dict())
        if len(core) > _MAX_CORE_BYTES:
            raise ValueError("linguistic checkpoint exceeds 512 MiB")
        manifest = {"schema": CHECKPOINT_SCHEMA, "profile_id": PROFILE_ID,
                    "lineage_id": self.LINEAGE_ID, "dimension": 8,
                    "core_file": "core.state.json", "core_sha256": _sha(core),
                    "core_bytes": len(core), "configuration": self._linguistic_options,
                    "effective_configuration": self._linguistic_effective_configuration,
                    "linguistic_identity": self._linguistic_identity,
                    "linguistic_identity_sha256": self._linguistic_identity_sha256,
                    "formula_head_present": False, **_FALSE}
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        # Exclusive directory creation reserves the bundle; the manifest is the
        # completion marker. A partial failed bundle is never loadable.
        with (root / "core.state.json").open("xb") as handle:
            handle.write(core)
        with (root / "manifest.json").open("xb") as handle:
            handle.write(_bytes(manifest))
        return json.loads(_bytes(manifest))


def load_training_checkpoint(directory):
    """Resume only an exact local linguistic profile bundle; never download."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("linguistic checkpoint requires a regular directory")
    manifest_raw = _read(root / "manifest.json", _MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_raw)
    expected_keys = {"schema", "profile_id", "lineage_id", "dimension", "core_file",
                     "core_sha256", "core_bytes", "configuration", "linguistic_identity",
                     "linguistic_identity_sha256", "effective_configuration", "formula_head_present", *_FALSE}
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ValueError("invalid linguistic checkpoint manifest fields")
    if (manifest["schema"] != CHECKPOINT_SCHEMA or manifest["profile_id"] != PROFILE_ID
            or manifest["lineage_id"] != Autoencoder.LINEAGE_ID
            or type(manifest["dimension"]) is not int or manifest["dimension"] != 8
            or manifest["core_file"] != "core.state.json"
            or manifest["formula_head_present"] is not False
            or any(manifest[name] is not False for name in _FALSE)):
        raise ValueError("incompatible linguistic checkpoint profile or authority")
    if _sha(_bytes(manifest["linguistic_identity"])) != manifest["linguistic_identity_sha256"]:
        raise ValueError("linguistic checkpoint identity digest mismatch")
    core = _read(root / "core.state.json", _MAX_CORE_BYTES)
    if _sha(core) != manifest["core_sha256"] or len(core) != manifest["core_bytes"]:
        raise ValueError("linguistic checkpoint core digest mismatch")
    config = manifest["configuration"]
    if not isinstance(config, dict) or "state" in config:
        raise ValueError("invalid linguistic constructor configuration")
    model = load_local_checkpoint(LinguisticAutoencoder, root / "core.state.json",
                                  expected_sha256=manifest["core_sha256"], **config)
    if model._linguistic_identity != manifest["linguistic_identity"]:
        raise ValueError("linguistic checkpoint backend, codec or source identity mismatch")
    if model._linguistic_effective_configuration != manifest["effective_configuration"]:
        raise ValueError("linguistic checkpoint effective constructor configuration mismatch")
    if _read(root / "manifest.json", _MAX_MANIFEST_BYTES) != manifest_raw:
        raise ValueError("linguistic checkpoint manifest changed during load")
    return model


__all__ = ["LinguisticAutoencoder", "load_training_checkpoint", "PROFILE_ID", "BACKENDS"]

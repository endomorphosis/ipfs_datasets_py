"""September 17 daemon codec and 8D numerical training, preserved side by side.

This profile retains the historical BM25/F-logic wrapper, including its known
semantic errors. Compiler-supervised repaired targets belong to the separate
LegacyLinguisticTeacher adapter; no latent-to-formula head may attach here.
Historical daemon defaults are explicit assumptions, not recovered checkpoint
producer CLI values. External consistency checks never constitute an admission.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, replace
import json
from pathlib import Path

from . import linguistic as _linguistic_facade
from .linguistic import (
    LinguisticAutoencoder, _bytes, _sha, _read, _FALSE, _model_package_identity,
    _MAX_CORE_BYTES, _MAX_MANIFEST_BYTES,
)
from ._daemon_snapshot import MANIFEST, MANIFEST_SHA256, verify_snapshot
from ._daemon_snapshot.codec import DeterministicModalLogicCodec, ModalLogicCodecConfig
from . import linguistic_cached as _cache_identity
from . import daemon_frame_scope as _frame_scope
from .. import _contract as _lineage_contract
from .._contract import load_local_checkpoint

PROFILE_ID = "legacy-daemon-linguistic-bm25-flogic-8d/v1"
CHECKPOINT_SCHEMA = "legacy-daemon-linguistic-training-checkpoint/v1"
SOURCE_REVISION = MANIFEST["source_revision"]
HISTORICAL_DEFAULTS = MANIFEST["constructor_fallbacks"]


def _source_paths():
    package = _lineage_contract._package_root()
    paths = [Path(__file__), Path(_linguistic_facade.__file__), Path(_cache_identity.__file__),
             Path(_lineage_contract.__file__), Path(_frame_scope.__file__),
             Path(__file__).parent / "__init__.py"]
    paths.extend(package / name for name in (
        "logic/integrations/typesafe_advisor.py",
        "logic/external_provers/lazy_installer.py",
        "logic/backends/installers/advisors.py"))
    return {str(path.relative_to(package)): path for path in paths}


def _stat_identity(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _codec_configuration(codec):
    selector = codec.frame_selector
    return json.loads(_bytes({"codec": asdict(codec.config), "flogic": asdict(codec.flogic_optimizer.config),
            "frame_selector": {"k1": selector.k1, "b": selector.b,
                "frames": [asdict(frame) for frame in selector.frames],
                "documents": selector._documents, "document_frequency": selector._doc_freq,
                "average_document_length": selector._avgdl}}))


def _registry_configuration(codec):
    return tuple(_cache_identity._registry_configuration(registry) for registry in (
        codec.registry, codec.parser.registry, codec.encoder.registry,
        codec.encoder._fallback_parser.registry, codec.compiler._fallback_parser.registry))


class HistoricalDaemonAutoencoder(LinguisticAutoencoder):
    """Original sparse trainer with its historical full feature-codec profile.

    The 71 daemon fallback settings are used by default. Explicit constructor
    overrides are preserved in the checkpoint identity and disclosed by describe.
    The deterministic 8D linguistic vector is a feature representation, not a
    verified semantic embedding. Original target-aware reconstruction remains.
    """

    # Correct the historical sample-ID/content alias without touching the
    # frozen numerical core. Fresh and resumed samples now address the same
    # derived-feature cache even when citation or section metadata changes.
    _sample_cache_for = _cache_identity.CachedLinguisticAutoencoder._sample_cache_for

    def __init__(self, *, state=None, compute_device="cpu", **legacy_options):
        forbidden = {"backend", "feature_codec", "formula_targets", "validation_formula_targets",
                     "formula_options", "formula_checkpoint", "joint_formula_checkpoint"}
        if forbidden & set(legacy_options):
            raise ValueError("historical daemon profile owns its blank-English codec; formula options are forbidden")
        verify_snapshot()
        settings = {**HISTORICAL_DEFAULTS, **legacy_options, "compute_device": compute_device}
        super().__init__(backend="historical_blank_en", state=state, **settings)
        self._sample_feature_cache = OrderedDict()
        self._numerical_cache_max_entries = 128
        # Use the exact explicit blank pipeline already identified by the base
        # profile, independently of a coincidentally installed missing-model name.
        encoder = self._linguistic_codec.encoder
        codec = DeterministicModalLogicCodec(ModalLogicCodecConfig(**MANIFEST["codec_configuration"]))
        codec.flogic_optimizer = _frame_scope.ObservationScopedFLogicOptimizer(
            config=codec.flogic_optimizer.config)
        codec.encoder = encoder
        self.feature_codec = self._linguistic_codec = codec
        self._daemon_configuration = json.loads(_bytes(_codec_configuration(codec)))
        self._daemon_registries = _registry_configuration(codec)
        self._daemon_components = (id(codec.parser), id(codec.registry), id(codec.compiler),
                                   id(codec.decoder), id(codec.frame_selector), id(codec.flogic_optimizer))
        self._daemon_constructor_options = {"compute_device": compute_device, **json.loads(_bytes(legacy_options))}
        self._runtime_source_paths = _source_paths()
        self._runtime_source_stats = {key: _stat_identity(path) for key, path in self._runtime_source_paths.items()}
        runtime_hashes = {key: _sha(path.read_bytes()) for key, path in self._runtime_source_paths.items()}
        self._linguistic_identity = {**self._linguistic_identity,
            "profile_id": PROFILE_ID, "source_revision": SOURCE_REVISION,
            "daemon_manifest_sha256": MANIFEST_SHA256,
            "daemon_codec_configuration": self._daemon_configuration,
            "profile_source_sha256": _sha(Path(__file__).read_bytes()),
            "cache_identity_source_sha256": _sha(Path(_cache_identity.__file__).read_bytes()),
            "numerical_cache_identity_policy": "complete-legal-sample-json/v1",
            "runtime_source_hashes": runtime_hashes,
            "historical_environment_reproduced": False,
            "producer_configuration_verified": False}
        self._linguistic_identity_sha256 = _sha(_bytes(self._linguistic_identity))
        self._linguistic_embedding_model = "linguistic:spacy-feature-hash8d:" + self._linguistic_identity_sha256

    def _require_profile(self):
        super()._require_profile()
        codec = self._linguistic_codec
        if (_codec_configuration(codec) != self._daemon_configuration
                or _registry_configuration(codec) != self._daemon_registries or
                (id(codec.parser), id(codec.registry), id(codec.compiler), id(codec.decoder),
                 id(codec.frame_selector), id(codec.flogic_optimizer)) != self._daemon_components):
            raise ValueError("historical daemon codec configuration changed")
        if any(_stat_identity(path) != self._runtime_source_stats[key]
               for key, path in self._runtime_source_paths.items()):
            raise ValueError("historical daemon shared runtime source changed")

    def describe(self):
        result = super().describe()
        result.update(training_profile=PROFILE_ID,
            feature_codec_scope="September 17 full deterministic modal/BM25/F-logic wrapper",
            historical_daemon_feature_codec_replay=True,
            historical_daemon_constructor_defaults=json.loads(_bytes(HISTORICAL_DEFAULTS)),
            explicit_constructor_overrides=json.loads(_bytes(self._daemon_constructor_options)),
            checkpoint_original_producer_configuration_verified=False,
            numerical_feature_cache={"identity_policy": "complete-legal-sample-json/v1",
                                     "max_entries": self._numerical_cache_max_entries, "byte_bound": None},
            flogic_frame_retention="per-observation temporary frames removed; preloaded frames preserved",
            external_prover_availability_reproduced=False)
        result["historical_environment_reproduced"] = False
        result["source_binding_scope"] = (
            "Frozen numerical/linguistic/daemon modules plus listed shared source hashes; "
            "optional observer, external prover availability, third-party packages and transitive services "
            "are not a recreation of the September runtime environment")
        return result

    def formula_decoder_description(self):
        return {"attached": False, "allowed": False, "profile_id": PROFILE_ID,
                "reason": "preserved_historical_daemon_profile", **_FALSE}

    def build_sample(self, **kwargs):
        sample = super().build_sample(**kwargs)
        return replace(sample, parser_trace={**sample.parser_trace,
            "linguistic_profile_id": PROFILE_ID,
            "historical_daemon_defaults_assumed": True,
            "historical_daemon_producer_verified": False})

    def linguistic_observation(self, sample):
        self._require_profile()
        self._samples([sample])
        codec = self._linguistic_codec
        result = codec.encode(sample.text, document_id=sample.sample_id, citation=sample.citation,
                              source=sample.source, source_embedding=sample.embedding_vector)
        return {"profile_id": PROFILE_ID, "backend": self.backend,
            "linguistic_identity_sha256": self._linguistic_identity_sha256,
            "source_sha256": _sha(sample.text.encode()), "encoding": result.encoding.to_dict(),
            "modal_ir": result.modal_ir.to_dict(),
            "decoded_feature_vector": codec.decoder.decode_embedding(result.encoding, dimensions=8),
            "wrapper_decoded_vector": list(result.decoded_embedding),
            "feature_keys": codec.feature_keys_for_sample(sample, max_features=self.max_codec_feature_keys),
            "frame_candidates": result.frame_candidates, "selected_frame": result.selected_frame,
            "kg_triples": result.kg_triples, "decoded_text": result.decoded_text,
            "decoded_modal_text": result.decoded_modal_text.to_dict(),
            "wrapper_losses": result.losses, "family_logits": result.family_logits,
            "target_family_distribution": result.target_family_distribution,
            "vector_origin": "deterministic_linguistic_feature_hash",
            "formula_origin": "historical_daemon_modal_ir_compiler",
            "source_copy_is_fidelity": False, "producer_configuration_verified": False, **_FALSE}

    def save_training_checkpoint(self, directory):
        self._require_profile()
        verify_snapshot()
        current = {**self._linguistic_identity,
                   **_model_package_identity(self.backend),
                   "cache_identity_source_sha256": _sha(Path(_cache_identity.__file__).read_bytes()),
                   "runtime_source_hashes": {key: _sha(path.read_bytes()) for key, path in self._runtime_source_paths.items()},
                   "profile_source_sha256": _sha(Path(__file__).read_bytes())}
        if current != self._linguistic_identity:
            raise ValueError("historical daemon source or backend changed")
        core = _bytes(self.state.to_dict())
        if len(core) > _MAX_CORE_BYTES:
            raise ValueError("historical daemon checkpoint exceeds 512 MiB")
        manifest = {"schema": CHECKPOINT_SCHEMA, "profile_id": PROFILE_ID,
            "lineage_id": self.LINEAGE_ID, "dimension": 8, "core_file": "core.state.json",
            "core_sha256": _sha(core), "core_bytes": len(core),
            "configuration": self._daemon_constructor_options,
            "effective_configuration": self._linguistic_effective_configuration,
            "linguistic_identity": self._linguistic_identity,
            "linguistic_identity_sha256": self._linguistic_identity_sha256,
            "formula_head_present": False, **_FALSE}
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        with (root / "core.state.json").open("xb") as handle:
            handle.write(core)
        with (root / "manifest.json").open("xb") as handle:
            handle.write(_bytes(manifest))
        return json.loads(_bytes(manifest))


def load_checkpoint(path, *, expected_sha256, **model_options):
    """Load existing local weights; source-era defaults remain an assumption."""
    return load_local_checkpoint(HistoricalDaemonAutoencoder, path,
                                 expected_sha256=expected_sha256, **model_options)


def load_training_checkpoint(directory):
    """Resume only a source-, configuration- and checksum-bound local bundle."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("historical daemon checkpoint requires a regular directory")
    manifest_raw = _read(root / "manifest.json", _MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_raw)
    expected = {"schema", "profile_id", "lineage_id", "dimension", "core_file", "core_sha256",
                "core_bytes", "configuration", "effective_configuration", "linguistic_identity",
                "linguistic_identity_sha256", "formula_head_present", *_FALSE}
    if (not isinstance(manifest, dict) or set(manifest) != expected
            or manifest["schema"] != CHECKPOINT_SCHEMA or manifest["profile_id"] != PROFILE_ID
            or manifest["lineage_id"] != HistoricalDaemonAutoencoder.LINEAGE_ID
            or type(manifest["dimension"]) is not int or manifest["dimension"] != 8
            or manifest["core_file"] != "core.state.json" or manifest["formula_head_present"] is not False
            or any(manifest[name] is not False for name in _FALSE)):
        raise ValueError("invalid historical daemon checkpoint manifest")
    if _sha(_bytes(manifest["linguistic_identity"])) != manifest["linguistic_identity_sha256"]:
        raise ValueError("historical daemon identity digest mismatch")
    core = _read(root / "core.state.json", _MAX_CORE_BYTES)
    if _sha(core) != manifest["core_sha256"] or len(core) != manifest["core_bytes"]:
        raise ValueError("historical daemon core digest mismatch")
    config = manifest["configuration"]
    if not isinstance(config, dict) or "state" in config:
        raise ValueError("invalid historical daemon constructor configuration")
    model = load_checkpoint(root / "core.state.json", expected_sha256=manifest["core_sha256"], **config)
    if (model._linguistic_identity != manifest["linguistic_identity"]
            or model._linguistic_effective_configuration != manifest["effective_configuration"]):
        raise ValueError("historical daemon checkpoint source, backend or configuration mismatch")
    if _read(root / "manifest.json", _MAX_MANIFEST_BYTES) != manifest_raw:
        raise ValueError("historical daemon manifest changed during load")
    return model


__all__ = ["HistoricalDaemonAutoencoder", "load_checkpoint", "load_training_checkpoint", "PROFILE_ID"]

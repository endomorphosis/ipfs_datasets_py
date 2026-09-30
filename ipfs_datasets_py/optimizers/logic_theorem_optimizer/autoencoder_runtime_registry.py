"""Explicit runtime versions over the existing legal and native feature APIs.

This is trusted local dispatch, not a plugin loader or a migration service.
Native versions reuse exact modality contracts and the single-owner DuckDB
registry. A registered candidate, reconstructed vector, or compiler target
does not acquire qualification, inference promotion, or proof authority.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re

from . import autoencoder_projection_features as features
from .autoencoder_modality_contracts import ModalityAdapterRegistry, ModalityContract


SCHEMA = "autoencoder-runtime-interface/v1"
NATIVE_DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir")
LEGAL_VERSIONS = ("legacy_v1", "legacy_v1_optimized", "current_v2")
LEARNED_FORMULA_VERSION = "source_conditioned_formula_v1"
MAX_CANDIDATE_BYTES = 32 * 1024 * 1024


class RuntimeVersionError(ValueError):
    """Unknown runtime, incompatible version, or unsupported interface operation."""


def _require(condition, message):
    if not condition:
        raise RuntimeVersionError(message)


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _optimizer_root():
    return Path(features.__file__).resolve().parent


def _source_identity(paths):
    # A limited, inspectable identity. This is deliberately not advertised as
    # provenance for transitive dependencies or the complete compiler tree.
    rows = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths}
    return {"files": rows, "sha256": features.digest(rows),
            "scope": "listed_runtime_files_only_not_transitive_dependency_provenance"}


def describe_runtime(domain, version):
    """Describe an exact selection; never infer a version from vector width."""
    root = _optimizer_root()
    paths = [("autoencoder_runtime_registry.py", Path(__file__))]
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        paths.extend((name, Path(__file__).with_name(name)) for name in
                     ("legal_formula_learning.py", "legal_formula_codec.py", "legal_formula_checkpoint.py"))
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
                "runtime_id": domain + ":" + version, "lineage_id": version,
                "input_representation": "source_text", "dimension": None,
                "state_schema": "learned-legal-formula-checkpoint/v1",
                "objective_default": "teacher_forced_formula_token_cross_entropy",
                "capabilities": ["train", "infer", "load_checkpoint", "decode_formal_logic",
                                 "register_candidate", "load_version"], "integrated": True,
                "formal_decoder": {"available": True, "modes": ["learned"],
                    "independent_learned_formula_decoder": True, "head_required": True,
                    "scope": "single_typed_deontic_rule_training_vocabulary"},
                "source_identity": _source_identity(paths), **features.FALSE}
    if domain == "legal_ir":
        _require(version in LEGAL_VERSIONS, "unknown legal runtime version")
        namespace = root / "autoencoder_lineages"
        profile = (namespace / (version + ".py") if version == "legacy_v1_optimized"
                   else namespace / version / "__init__.py")
        _require(profile.is_file(), "runtime profile is not installed: " + version)
        paths.extend([("autoencoder_lineages/" + str(profile.relative_to(namespace)), profile),
                      ("autoencoder_lineages/_contract.py", namespace / "_contract.py")])
        legacy = version != "current_v2"
        if legacy:
            paths.append(("autoencoder_lineages/legacy_v1/_snapshot/MANIFEST.json",
                          namespace / "legacy_v1/_snapshot/MANIFEST.json"))
        else:
            paths.append(("modal_autoencoder.py", root / "modal_autoencoder.py"))
        result = {"lineage_id": "legacy_hub_v1" if legacy else "current_legal_v2",
                  "input_representation": "explicit_8d_vectors" if legacy else "explicit_384d_vectors",
                  "dimension": 8 if legacy else 384, "state_schema": "modal-autoencoder-state/json",
                  "objective_default": "historical_reconstruction" if legacy else "raw_decoder",
                  "capabilities": ["train", "infer", "load_checkpoint", "decode_formal_logic"], "integrated": True,
                  "formal_decoder": {"available": True, "modes": ["guided_compiler", "canonical_compiler"],
                                     "independent_learned_formula_decoder": False, "head_required": False}}
        paths.append(("legal_formal_decoder.py", Path(__file__).with_name("legal_formal_decoder.py")))
    else:
        _require(domain in NATIVE_DOMAINS, "unknown modality domain")
        _require(version in ("native_v1", "native_v2"), "unknown native runtime version")
        module_name = "autoencoder_projection_features" + ("_v2" if version == "native_v2" else "")
        paths.extend([(module_name + ".py", root / (module_name + ".py")),
                      ("modal_autoencoder_cuda.py", root / "modal_autoencoder_cuda.py")])
        integrated = version == "native_v1"
        result = {"lineage_id": domain + "/native_projection_features",
                  "input_representation": "native_compiler_structural_features",
                  "dimension": None, "state_schema": "native-projection-feature-state/" + version[-2:],
                  "objective_default": "native-projection-reconstruction/v1",
                  "capabilities": ["prepare_targets", "train", "infer", "register_candidate", "load_version", "decode_formal_logic"]
                                  if integrated else [], "integrated": integrated,
                  "formal_decoder": {"available": True, "modes": ["reconstructed_features"],
                                     "head_required": True, "factory": "open_formal_decoder",
                                     "input_is_compiler_targets": True}}
        paths.append(("native_formal_decoder.py", Path(__file__).with_name("native_formal_decoder.py")))
        if not integrated:
            result["unsupported_reason"] = ("Streamed v2 has its own minibatch/Adam state. Its exact modality "
                "contract and registry resume adapter are not implemented by this interface.")
    return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
            "runtime_id": domain + ":" + version, "source_identity": _source_identity(paths),
            **result, **features.FALSE}


def list_runtimes():
    """List installed profiles, with unavailable integrations clearly marked."""
    namespace = _optimizer_root() / "autoencoder_lineages"
    legal = [version for version in LEGAL_VERSIONS if
             ((namespace / (version + ".py")) if version == "legacy_v1_optimized"
              else (namespace / version / "__init__.py")).is_file()]
    return [describe_runtime("legal_ir", version) for version in (*legal, LEARNED_FORMULA_VERSION)] + [
        describe_runtime(domain, version) for domain in NATIVE_DOMAINS
        for version in ("native_v1", "native_v2")]


def _target_adapter(domain):
    from ...logic.formalization.autoencoder import domain_targets, ui_targets
    _require(domain in NATIVE_DOMAINS, "native target preparation requires a native domain")
    if domain == "ui_ux_ir":
        return ui_targets, ui_targets.prepare_ui_targets
    return domain_targets, {"intent_ir": domain_targets.prepare_intent_targets,
                            "security_ir": domain_targets.prepare_security_targets}[domain]


def prepare_targets(domain, version, **inputs):
    """Delegate to the domain's typed compiler/validator, preserving its views."""
    descriptor = describe_runtime(domain, version)
    _require("prepare_targets" in descriptor["capabilities"], "runtime lacks prepare_targets")
    return _target_adapter(domain)[1](**inputs)


class _NativeAdapter:
    def __init__(self, contract, space):
        self.contract, self.space = contract, _copy(space)

    def train(self, samples, validation_samples, **options):
        return features.train_projection_features(self.contract, self.space, samples,
                                                  validation_samples, **options)

    def evaluate(self, state, samples):
        return features.infer_projection_features(self.contract, self.space, state, samples)


class NativeRuntime:
    """One exact domain, feature basis, objective, validator policy and state codec.

    Training selects a private candidate. Inference never trains. Registry
    publication records ancestry, but does not promote a qualified model head.
    """
    def __init__(self, domain, *, contract, feature_space, state=None, decoder_head=None):
        _require(type(contract) is ModalityContract, "typed modality contract required")
        _require(contract.domain == domain, "contract belongs to another domain")
        self._descriptor = describe_runtime(domain, "native_v1")
        self.contract, self._space = contract, _copy(feature_space)
        features._contract(contract, self._space)
        _require(contract.adapter.identifier == "native-domain-target-adapter" and contract.adapter.version == "1"
                 and contract.optimizer.version == "1"
                 and re.fullmatch(r"1:latent-([1-9]|[1-5][0-9]|6[0-4])", contract.state_codec.version),
                 "implementation version labels differ from native_v1")
        self._verify_adapter()
        self._adapters = ModalityAdapterRegistry()
        self._adapters.register(contract, _NativeAdapter(contract, self._space), capabilities=("train", "evaluate"))
        self._state = None if state is None else _copy(state)
        if state is not None:
            features._validate_state(contract, self._space, self._state)
        self._parent_version_id = None
        self._result = None
        self._decoder_head = None if decoder_head is None else _copy(decoder_head)
        if self._decoder_head is not None:
            from .native_formal_decoder import validate_decoder
            validate_decoder(self._space, self._decoder_head)

    def _verify_adapter(self):
        contract = self.contract
        domain = contract.domain
        adapter, _ = _target_adapter(domain)
        _require(contract.adapter.sha256 == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
                 "installed native target adapter differs from contract")

    def describe(self):
        variant_id = self.contract.variant_id
        if self._decoder_head is not None:
            from .native_formal_checkpoint import formal_variant_id
            variant_id = formal_variant_id(self.contract, self._decoder_head)
        return {**_copy(self._descriptor), "contract": self.contract.to_dict(),
                "contract_sha256": self.contract.sha256, "variant_id": variant_id,
                "numerical_variant_id": self.contract.variant_id,
                "parent_version_id": self._parent_version_id,
                "decoder_head_sha256": None if self._decoder_head is None else features.digest(self._decoder_head),
                "decoder_head_present": self._decoder_head is not None}

    @property
    def feature_space(self):
        return _copy(self._space)

    @property
    def decoder_head(self):
        return None if self._decoder_head is None else _copy(self._decoder_head)

    @property
    def state(self):
        return None if self._state is None else _copy(self._state)

    def train(self, samples, *, validation_samples, **options):
        _require(self._result is None, "register the pending candidate before training another version")
        _require("base_state" not in options, "resume state is bound to this runtime; use load_version")
        self._verify_adapter()
        if self._decoder_head is not None:
            from .native_formal_decoder import validate_decoder
            validate_decoder(self._space, self._decoder_head)
        adapter = self._adapters.resolve(self.contract, required_capabilities=("train",))
        options.setdefault("latent_width", int(self.contract.state_codec.version.split("latent-")[1]))
        result = adapter.train(samples, validation_samples, base_state=self._state, **options)
        self._result, self._state = _copy(result), _copy(result["state"])
        return result

    def infer(self, samples, **options):
        _require(not options, "native inference does not accept training or legal evaluation options")
        _require(self._state is not None, "native inference requires a trained or loaded state")
        self._verify_adapter()
        return self._adapters.resolve(self.contract, required_capabilities=("evaluate",)).evaluate(self._state, samples)

    def register_candidate(self, registry, directory):
        _require(self._result is not None, "train a candidate before registering it")
        self._verify_adapter()
        if self._decoder_head is None:
            result = features.register_feature_candidate(registry, self.contract, self._space, self._result,
                                                        directory, parent_version_id=self._parent_version_id)
        else:
            from .native_formal_checkpoint import register_formal_candidate
            result = register_formal_candidate(registry, self.contract, self._space, self._result,
                self._decoder_head, directory, parent_version_id=self._parent_version_id)
        self._parent_version_id = result["version_id"]
        self._result = None
        return {**result, "runtime_id": self._descriptor["runtime_id"]}

    def decode_formal_logic(self, samples, *, decoder_head=None, mode="reconstructed_features"):
        """Decode model scores using a fitted structural head; never substitute input targets."""
        _require(mode == "reconstructed_features", "native decoder mode must be reconstructed_features")
        head = self._decoder_head if decoder_head is None else _copy(decoder_head)
        if head is None:
            return _missing_head(self.contract.domain, "native_v1")
        from .native_formal_decoder import decode_formal_features, validate_decoder
        validate_decoder(self._space, head)
        return decode_formal_features(self._space, head, self.infer(samples))


class LegalRuntime:
    """Legal features and explicitly attributed compiler-backed formal candidates."""
    def __init__(self, version, *, checkpoint=None, expected_sha256=None, **model_options):
        self._descriptor = describe_runtime("legal_ir", version)
        # The module name is selected solely from the closed local enum above.
        namespace = importlib.import_module(__package__ + ".autoencoder_lineages." + version)
        if checkpoint is None:
            _require(expected_sha256 is None, "checkpoint hash supplied without a checkpoint")
            self.model = namespace.Autoencoder(**model_options)
        else:
            self.model = namespace.load_checkpoint(checkpoint, expected_sha256=expected_sha256, **model_options)

    def describe(self):
        return {**_copy(self._descriptor), "model": self.model.describe()}

    def train(self, samples, *, validation_samples=None, **options):
        return self.model.train_generalizable_projection(samples, validation_samples=validation_samples, **options)

    def infer(self, samples, **options):
        return self.model.evaluate(samples, **options)

    def decode_formal_logic(self, samples, *, mode="guided_compiler", **options):
        from .legal_formal_decoder import decode_legal_formulas
        return decode_legal_formulas(self.model, samples, mode=mode, **options)


class LearnedFormulaRuntime:
    """A separate source-conditioned model; old legal weights are never converted."""
    def __init__(self, *, checkpoint=None, expected_sha256=None):
        from . import legal_formula_learning as learning
        self._checkpoint = None
        if checkpoint is not None:
            if isinstance(checkpoint, (str, Path)):
                self._checkpoint = learning.load_checkpoint(checkpoint, expected_sha256=expected_sha256)
            else:
                _require(expected_sha256 is None, "in-memory checkpoints do not accept a file hash")
                learning.validate_checkpoint(checkpoint)
                self._checkpoint = _copy(checkpoint)
        else:
            _require(expected_sha256 is None, "checkpoint hash supplied without checkpoint")
        self._decoder = None
        self._result = None
        self._parent_version_id = None

    @property
    def checkpoint(self):
        return None if self._checkpoint is None else _copy(self._checkpoint)

    def describe(self):
        from . import legal_formula_learning as learning
        return {**describe_runtime("legal_ir", LEARNED_FORMULA_VERSION),
                "checkpoint_sha256": None if self._checkpoint is None else learning.checkpoint_digest(self._checkpoint),
                "parent_version_id": self._parent_version_id,
                "checkpoint_present": self._checkpoint is not None,
                "trained_checkpoint_present": self._checkpoint is not None
                    and self._checkpoint["progress"]["optimizer_steps"] > 0}

    def train(self, samples, *, validation_samples, **options):
        from . import legal_formula_learning as learning
        _require(self._result is None, "register the pending candidate before training another version")
        _require("checkpoint" not in options, "resume checkpoint is bound to this runtime")
        result = learning.train_decoder(samples, validation_samples, checkpoint=self._checkpoint, **options)
        self._checkpoint, self._result = _copy(result["checkpoint"]), _copy(result)
        self._decoder = None
        return result

    def decode_formal_logic(self, samples, *, mode="learned"):
        from . import legal_formula_learning as learning
        _require(mode == "learned", "source-conditioned formula runtime supports only learned mode")
        _require(self._checkpoint is not None, "train or load a learned formula checkpoint before inference")
        if self._decoder is None:
            self._decoder = learning.LearnedLegalFormulaDecoder(self._checkpoint)
        return self._decoder.decode_formal_logic(samples)

    def infer(self, samples):
        return self.decode_formal_logic(samples)

    def register_candidate(self, registry, directory):
        from .legal_formula_checkpoint import register_candidate
        _require(self._result is not None, "train a candidate before registering it")
        result = register_candidate(registry, self._result, directory, parent_version_id=self._parent_version_id)
        self._parent_version_id = result["version_id"]
        self._result = None
        return {**result, "runtime_id": "legal_ir:" + LEARNED_FORMULA_VERSION}


def open_runtime(domain, version, **binding):
    """Select explicitly. Dimensions, source metadata, and filenames never dispatch."""
    descriptor = describe_runtime(domain, version)
    _require(descriptor["integrated"], descriptor.get("unsupported_reason", "runtime is not integrated"))
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        return LearnedFormulaRuntime(**binding)
    if domain == "legal_ir":
        return LegalRuntime(version, **binding)
    return NativeRuntime(domain, **binding)


def build_native_runtime(domain, version, training_targets, *, projection_ids, ir_schema, latent_width=4,
                         with_formal_decoder=True):
    """Build a v1 basis from training only; excluded native views remain recorded."""
    descriptor = describe_runtime(domain, version)
    _require(domain in NATIVE_DOMAINS and descriptor["integrated"], "native version is not integrated")
    adapter, _ = _target_adapter(domain)
    space = features.build_feature_space(domain, projection_ids, training_targets)
    contract = features.build_native_feature_contract(space, ir_schema=ir_schema,
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(), latent_width=latent_width)
    _require(type(with_formal_decoder) is bool, "with_formal_decoder must be boolean")
    head = None
    if with_formal_decoder:
        from .native_formal_decoder import train_formal_decoder
        head = train_formal_decoder(space, training_targets)
    return open_runtime(domain, version, contract=contract, feature_space=space, decoder_head=head)


def _read_candidate(registry, version):
    from ...duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA, content_identity
    expected_version = content_identity({"schema": REGISTRY_SCHEMA, **{
        key: version[key] for key in ("variant_id", "artifact", "metadata", "parent_version_id")}})
    _require(version["version_id"] == expected_version, "registry version content identity differs")
    artifact = registry.verify_artifact(version["artifact"])
    _require(artifact["bytes"] <= MAX_CANDIDATE_BYTES, "native candidate exceeds interface byte bound")
    with registry.artifact_path(artifact).open("rb") as stream:
        raw = stream.read(MAX_CANDIDATE_BYTES + 1)
    _require(len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
             "candidate changed after artifact verification")
    saved = json.loads(raw)
    _require(type(saved) is dict and set(saved) == {"contract", "feature_space", "state", "report"},
             "unsupported native candidate envelope")
    return saved


def load_version(registry, version_id, *, domain, version):
    """Verify and reload a native candidate from the existing DuckDB registry.

    The caller selects the expected domain/version. Metadata cannot select
    imports, replace projections, migrate Adam state, or raise authority.
    """
    descriptor = describe_runtime(domain, version)
    _require("load_version" in descriptor["capabilities"], "runtime lacks registry load_version")
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        from .legal_formula_checkpoint import load_registered_candidate
        saved = load_registered_candidate(registry, version_id)
        runtime = LearnedFormulaRuntime(checkpoint=saved["checkpoint"])
        runtime._parent_version_id = version_id
        return runtime
    row = registry.get_version(version_id)
    if "decoder_head_sha256" in row["metadata"]:
        from .native_formal_checkpoint import FormalCandidateError, load_formal_candidate
        try:
            saved = load_formal_candidate(registry, version_id, domain)
        except FormalCandidateError as exc:
            raise RuntimeVersionError(str(exc)) from exc
        runtime = open_runtime(domain, version, contract=saved["contract"], feature_space=saved["feature_space"],
                               state=saved["state"], decoder_head=saved["decoder_head"])
        runtime._parent_version_id = version_id
        return runtime
    saved = _read_candidate(registry, row)
    contract = ModalityContract.from_dict(saved["contract"])
    _require(row["variant_id"] == contract.variant_id, "registry variant differs from candidate contract")
    manifest = registry.get_variant(row["variant_id"])["manifest"]
    _require(manifest == contract.registry_manifest(), "registry modality manifest differs from candidate")
    _require(row["metadata"] == {"contract_sha256": contract.sha256,
             "training_purpose": "feature_pretraining", **features.FALSE}, "candidate metadata differs")
    report, state = saved["report"], saved["state"]
    _require(report["contract_sha256"] == contract.sha256
             and report["feature_space_sha256"] == features.digest(saved["feature_space"])
             and all(report.get(key) is False for key in features.FALSE), "candidate report identity or authority differs")
    parent_id = row["parent_version_id"]
    if parent_id is None:
        _require(report["base_state_sha256"] is None, "resumed candidate lacks a registry parent")
    else:
        parent = registry.get_version(parent_id)
        _require(parent["variant_id"] == row["variant_id"], "parent belongs to another variant")
        parent_saved = _read_candidate(registry, parent)
        _require(features.digest(parent_saved["state"]) == report["base_state_sha256"],
                 "candidate numerical parent differs from registry parent")
    runtime = open_runtime(domain, version, contract=contract, feature_space=saved["feature_space"], state=state)
    runtime._parent_version_id = row["version_id"]
    return runtime


def _missing_head(domain, version):
    return {"schema": "autoencoder-formal-decoder-unavailable/v1", "domain": domain,
            "runtime_version": version, "status": "decoder_head_required", "rows": [],
            "formula_count": 0, "decoded_formulas_generated": False,
            "reason": "Fit train_formal_decoder on the original training targets and pass its head explicitly; this checkpoint has no structural decoder schema.",
            **features.FALSE}


class StreamedFormalRuntime:
    """Read-only v2 decoding; the v2 training/registry adapter remains separate."""
    def __init__(self, domain, *, feature_space, state, decoder_head=None):
        from . import autoencoder_projection_features_v2 as backend
        _require(domain in NATIVE_DOMAINS and feature_space.get("domain_id") == domain,
                 "streamed feature space belongs to another domain")
        self._space, self._state = _copy(feature_space), _copy(state)
        backend._validate_state(self._space, self._state)
        self._domain = domain
        self._head = None if decoder_head is None else _copy(decoder_head)
        if self._head is not None:
            from .native_formal_decoder import validate_decoder
            validate_decoder(self._space, self._head)

    def describe(self):
        return {**describe_runtime(self._domain, "native_v2"), "session_capabilities": ["infer", "decode_formal_logic"],
                "decoder_head_present": self._head is not None,
                "state_sha256": features.digest(self._state), "feature_space_sha256": features.digest(self._space)}

    def infer(self, samples):
        from .autoencoder_projection_features_v2 import infer_streamed_projection_features
        return infer_streamed_projection_features(self._space, self._state, samples)

    def decode_formal_logic(self, samples, *, decoder_head=None, mode="reconstructed_features"):
        _require(mode == "reconstructed_features", "native decoder mode must be reconstructed_features")
        head = self._head if decoder_head is None else _copy(decoder_head)
        if head is None:
            return _missing_head(self._domain, "native_v2")
        from .native_formal_decoder import infer_and_decode_native_v2
        return infer_and_decode_native_v2(self._space, self._state, head, samples)


def open_formal_decoder(domain, version, **binding):
    """One explicit formal-output factory, including the v2 read-only decoder."""
    describe_runtime(domain, version)  # closed trusted-local dispatch
    if domain in NATIVE_DOMAINS and version == "native_v2":
        return StreamedFormalRuntime(domain, **binding)
    return open_runtime(domain, version, **binding)


__all__ = ["RuntimeVersionError", "list_runtimes", "describe_runtime", "prepare_targets",
           "open_runtime", "build_native_runtime", "load_version", "open_formal_decoder",
           "NativeRuntime", "LegalRuntime", "StreamedFormalRuntime", "LearnedFormulaRuntime",
           "LEARNED_FORMULA_VERSION"]

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
CODEBASE_DOMAIN = "codebase_ir"
CODEBASE_FEATURE_VERSION = "codebase_feature_v1"
CODEBASE_SOURCE_FEATURE_VERSION = "source_bound_feature_v1"
CODEBASE_SOURCE_FEATURE_SCHEMA = "codebase-ir-source-bound-feature-targets@1"
LEGAL_VERSIONS = ("legacy_v1", "legacy_v1_optimized", "current_v2")
LEARNED_FORMULA_VERSION = "source_conditioned_formula_v1"
GROUPED_FORMULA_VERSION = "source_conditioned_grouped_v2"
NATIVE_FORMULA_VERSION = "native_formula_v1"
PUBLISHED_384_VERSION = "published_384_v1"
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
    if domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION:
        from .autoencoder_logic_requirements import describe_logic_requirements
        adapter, _ = _source_bound_codebase_adapter()
        paths = [("autoencoder_runtime_registry.py", Path(__file__)),
                 ("autoencoder_logic_requirements.py", root / "autoencoder_logic_requirements.py"),
                 ("autoencoder_projection_features.py", root / "autoencoder_projection_features.py"),
                 ("modal_autoencoder_cuda.py", root / "modal_autoencoder_cuda.py"),
                 ("logic/software_contracts/codebase_ir_targets.py", Path(adapter.__file__))]
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
                "runtime_id": domain + ":" + version, "lineage_id": domain + "/" + version,
                "input_representation": "source_bound_program_ir_structural_features", "dimension": None,
                "latent_width_default": 8, "supported_latent_widths": {"minimum": 1, "maximum": 64},
                "state_schema": features.STATE_SCHEMA, "target_schema": CODEBASE_SOURCE_FEATURE_SCHEMA,
                "objective_default": "native-projection-reconstruction/v1",
                "capabilities": ["prepare_targets", "train", "infer", "register_candidate", "load_version"],
                "integrated": True, "training_purpose": "feature_pretraining",
                "formal_decoder": {"available": False, "modes": [],
                                   "scope": "numerical_structural_reconstruction_only"},
                "resource_policy": "low-level cooperative CPU backend; current-source coordinator owns isolated resource admission and cancellation",
                "qualification_requirements": describe_logic_requirements(domain),
                "source_custody_owner": "native_codebase_target_adapter_and_training_coordinator",
                "runtime_behavior_proved": False, "kernel_checked": False,
                "planner_admission_eligible": False, "cache_authoritative": False,
                "source_identity": _source_identity(paths), **features.FALSE}
    if domain == CODEBASE_DOMAIN:
        _require(version == CODEBASE_FEATURE_VERSION, "unknown codebase runtime version")
        from ...logic.formalization.autoencoder import codebase_targets
        paths = [("autoencoder_runtime_registry.py", Path(__file__)),
                 ("autoencoder_projection_features.py", root / "autoencoder_projection_features.py"),
                 ("autoencoder_modality_contracts.py", root / "autoencoder_modality_contracts.py"),
                 ("codebase_targets.py", Path(codebase_targets.__file__))]
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
                "runtime_id": domain + ":" + version, "lineage_id": domain + "/" + version,
                "input_representation": "captured_integer_model_structural_features", "dimension": None,
                "state_schema": features.STATE_SCHEMA, "objective_default": "native-projection-reconstruction/v1",
                "capabilities": ["prepare_targets", "train", "infer", "register_candidate", "load_version"],
                "integrated": True, "training_purpose": "feature_pretraining",
                "formal_decoder": {"available": False, "modes": [], "head_required": True,
                                   "scope": "feature reconstruction only; no formula/property decoder"},
                "unknown_atom_policy": "frozen basis reports omitted atoms; different unseen literals can collide; no semantic discrimination guarantee",
                "resource_policy": "low-level cooperative CPU backend; current-source owner wrapper supplies isolated resource admission and cancellation",
                "qualification_requirements": {
                    "domain": domain, "qualified": False, "admitted": False,
                    "qualification_gaps": ["source runtime semantics", "learned formal decoding",
                                           "held-out semantic accuracy", "model head promotion", "proof authority"],
                    "scope": codebase_targets.TARGET_PROFILE},
                "source_identity": _source_identity(paths), **features.FALSE}
    _require(domain == "legal_ir" or domain in NATIVE_DOMAINS, "unknown modality domain")
    from .autoencoder_logic_requirements import describe_logic_requirements
    requirements = describe_logic_requirements(domain)
    paths = [("autoencoder_runtime_registry.py", Path(__file__)),
             ("autoencoder_logic_requirements.py", root / "autoencoder_logic_requirements.py")]
    if version == PUBLISHED_384_VERSION:
        from ...logic.formalization.autoencoder.checkpoint_hub import RUNTIMES
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
                "runtime_id": domain + ":" + version, "lineage_id": RUNTIMES[domain],
                "input_representation": "gte_small_384d_source_embeddings", "dimension": 384,
                "state_schema": "ir-384-hub-package/v1", "integrated": True,
                "capabilities": ["load_checkpoint", "infer"], "release_stage": "development",
                "source_identity": _source_identity(paths),
                "qualification_requirements": requirements, **features.FALSE}
    if domain in NATIVE_DOMAINS and version == NATIVE_FORMULA_VERSION:
        paths.extend((name, Path(__file__).with_name(name)) for name in (
            "native_formula_training.py", "native_formula_checkpoint.py"))
        paths.append(("native_formal_decoder.py", root / "native_formal_decoder.py"))
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
            "runtime_id": domain + ":" + version, "lineage_id": domain + "/" + version,
            "input_representation": "native_compiler_structural_features", "dimension": None,
            "state_schema": "native-formula-checkpoint/v1",
            "objective_default": "native-path-value-cross-entropy/v1",
            "capabilities": ["prepare_targets", "train", "infer", "load_checkpoint", "decode_formal_logic",
                             "register_candidate", "load_version"], "integrated": True,
            "formal_decoder": {"available": True, "modes": ["learned_fields"], "head_required": True,
                "trained_neural_decoder": True, "input_is_compiler_targets": True,
                "independent_learned_formula_decoder": False,
                "scope": "fixed_shape_native_records_training_path_value_vocabulary"},
            "source_identity": _source_identity(paths), "qualification_requirements": requirements,
            **features.FALSE}
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        paths.extend((name, root / name) for name in
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
                "source_identity": _source_identity(paths),
                "qualification_requirements": requirements, **features.FALSE}
    if domain == "legal_ir" and version == GROUPED_FORMULA_VERSION:
        # Discovery reads identities without importing Torch or loading weights.
        paths.extend((name, root.parent.parent / name) for name in (
            "logic/formalization/autoencoder/legal_grouped_span_decoder_v2.py",
            "logic/deontic/coordination_decoder.py"))
        return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
                "runtime_id": domain + ":" + version, "lineage_id": version,
                "input_representation": "source_text_and_explicit_caller_modal_scope", "dimension": None,
                "input_fields": ["source_text", "modal_scope"], "numeric_vector_conditioning": False,
                "caller_modal_scope_required_for_prediction": True,
                "state_schema": "legal-grouped-span-decoder-checkpoint/v2",
                "output_schema": "legal-coordination-decode-request/v1",
                "capabilities": ["load_checkpoint", "infer", "decode_formal_logic"],
                "integrated": True, "experimental": True, "release_stage": "experimental",
                "formal_decoder": {"available": True, "modes": ["learned_grouped"],
                    "independent_learned_formula_decoder": True, "head_required": True,
                    "scope": "ordered_2_to_8_actor_modality_action_members_with_declared_modal_scope",
                    "member_count": {"minimum": 2, "maximum": 8},
                    "connective": "inclusive_or", "binding_profile": "universal_actor_predicate"},
                "supported_logic_families": ["deontic_fol"],
                "all_family_requirements_satisfied": False,
                "source_conditioned": True, "latent_conditioned": False,
                "source_semantics_verified": False, "proof_ready": False,
                "source_identity": _source_identity(paths),
                "qualification_requirements": requirements, **features.FALSE}
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
                                     "independent_learned_formula_decoder": False, "head_required": False,
                                     "optional_learned_latent_mode": "learned_latent",
                                     "learned_latent_head_requires_joint_training": True,
                                     "joint_training_scope": "residual_projection_and_formula_head_with_frozen_sparse_core"}}
        paths.append(("legal_formal_decoder.py", root / "legal_formal_decoder.py"))
        paths.extend((name, root / name) for name in ("modal_joint_formula.py", "modal_latent_formula.py"))
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
        paths.append(("native_formal_decoder.py", root / "native_formal_decoder.py"))
        if not integrated:
            result["unsupported_reason"] = ("Streamed v2 has its own minibatch/Adam state. Its exact modality "
                "contract and registry resume adapter are not implemented by this interface.")
    return {"schema": SCHEMA, "domain": domain, "runtime_version": version,
            "runtime_id": domain + ":" + version, "source_identity": _source_identity(paths),
            **result, "qualification_requirements": requirements, **features.FALSE}


def list_runtimes():
    """List installed profiles, with unavailable integrations clearly marked."""
    namespace = _optimizer_root() / "autoencoder_lineages"
    legal = [version for version in LEGAL_VERSIONS if
             ((namespace / (version + ".py")) if version == "legacy_v1_optimized"
              else (namespace / version / "__init__.py")).is_file()]
    return [describe_runtime(domain, PUBLISHED_384_VERSION) for domain in ("legal_ir", *NATIVE_DOMAINS)] + [
        describe_runtime("legal_ir", version) for version in (*legal, LEARNED_FORMULA_VERSION, GROUPED_FORMULA_VERSION)] + [
        describe_runtime(domain, version) for domain in NATIVE_DOMAINS
        for version in ("native_v1", "native_v2", NATIVE_FORMULA_VERSION)] + [
        describe_runtime(CODEBASE_DOMAIN, CODEBASE_FEATURE_VERSION),
        describe_runtime(CODEBASE_DOMAIN, CODEBASE_SOURCE_FEATURE_VERSION)]


def _target_adapter(domain):
    if domain == CODEBASE_DOMAIN:
        from ...logic.formalization.autoencoder import codebase_targets
        return codebase_targets, codebase_targets.prepare_codebase_targets
    from ...logic.formalization.autoencoder import domain_targets, ui_targets
    _require(domain in NATIVE_DOMAINS, "native target preparation requires a native domain")
    if domain == "ui_ux_ir":
        return ui_targets, ui_targets.prepare_ui_targets
    return domain_targets, {"intent_ir": domain_targets.prepare_intent_targets,
                            "security_ir": domain_targets.prepare_security_targets}[domain]


def _source_bound_codebase_adapter():
    from ...logic.software_contracts import codebase_ir_targets
    return codebase_ir_targets, codebase_ir_targets.prepare_codebase_targets


def prepare_targets(domain, version, **inputs):
    """Delegate to the domain's typed compiler/validator, preserving its views."""
    descriptor = describe_runtime(domain, version)
    _require("prepare_targets" in descriptor["capabilities"], "runtime lacks prepare_targets")
    if domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION:
        return _source_bound_codebase_adapter()[1](**inputs)
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
    def __init__(self, domain, *, contract, feature_space, state=None, decoder_head=None,
                 _runtime_version="native_v1"):
        _require(type(contract) is ModalityContract, "typed modality contract required")
        _require(contract.domain == domain, "contract belongs to another domain")
        self._descriptor = describe_runtime(domain, _runtime_version)
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
        adapter, _ = (_source_bound_codebase_adapter() if domain == CODEBASE_DOMAIN
                      and self._descriptor["runtime_version"] == CODEBASE_SOURCE_FEATURE_VERSION
                      else _target_adapter(domain))
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


def _codebase_targets(samples):
    from ...logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    adapter, _ = _target_adapter(CODEBASE_DOMAIN)
    _require(type(samples) in (list, tuple) and 1 <= len(samples) <= 1024,
             "codebase target batch must be a bounded nonempty list or tuple")
    result = []
    for sample in samples:
        target = sample if type(sample) is DomainTargetEnvelope else DomainTargetEnvelope.from_dict(sample)
        result.append(adapter.validate_codebase_targets(target))
    return result


class CodebaseFeatureRuntime:
    """One frozen integer-model feature basis and exact Adam lineage.

    This low-level API accepts captured replayable targets, not a live checkout.
    It neither observes structural heads nor grants source or proof authority.
    The current-source wrapper owns resource isolation and cohort/role fences.
    """

    def __init__(self, *, contract, feature_space, state=None):
        _require(type(contract) is ModalityContract and contract.domain == CODEBASE_DOMAIN,
                 "codebase runtime requires its exact modality contract")
        self.contract, self._space = contract, _copy(feature_space)
        self._descriptor = describe_runtime(CODEBASE_DOMAIN, CODEBASE_FEATURE_VERSION)
        adapter, _ = _target_adapter(CODEBASE_DOMAIN)
        _require(contract.ir_schema == adapter.TARGET_PROFILE
                 and self._space.get("projection_ids") == [adapter.PROJECTION_ID],
                 "codebase feature runtime requires its closed integer-model projection")
        features._contract(contract, self._space)
        _require(contract.adapter.identifier == "native-domain-target-adapter" and contract.adapter.version == "1"
                 and contract.optimizer.version == "1"
                 and re.fullmatch(r"1:latent-([1-9]|[1-5][0-9]|6[0-4])", contract.state_codec.version),
                 "implementation labels differ from codebase_feature_v1")
        self._verify_adapter()
        self._state = None if state is None else _copy(state)
        if state is not None:
            features._validate_state(contract, self._space, self._state)
        self._parent_version_id = None
        self._result = None
        self._training_report = None

    def _verify_adapter(self):
        adapter, _ = _target_adapter(CODEBASE_DOMAIN)
        _require(self.contract.adapter.sha256 == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
                 "installed codebase target adapter differs from contract")

    @property
    def feature_space(self):
        return _copy(self._space)

    @property
    def state(self):
        return None if self._state is None else _copy(self._state)

    @property
    def training_report(self):
        """Historical metadata, including owner-added cohort bindings, unchanged."""
        return None if self._training_report is None else _copy(self._training_report)

    @property
    def parent_version_id(self):
        return self._parent_version_id

    def describe(self):
        return {**_copy(self._descriptor), "contract": self.contract.to_dict(),
                "contract_sha256": self.contract.sha256, "variant_id": self.contract.variant_id,
                "parent_version_id": self._parent_version_id,
                "latent_width": int(self.contract.state_codec.version.split("latent-")[1])}

    def train(self, samples, *, validation_samples, **options):
        _require(self._result is None, "register the pending candidate before training another version")
        _require("base_state" not in options, "resume state is bound to this runtime; use load_version")
        self._verify_adapter()
        samples, validation_samples = _codebase_targets(samples), _codebase_targets(validation_samples)
        options.setdefault("latent_width", int(self.contract.state_codec.version.split("latent-")[1]))
        result = features.train_projection_features(self.contract, self._space, samples, validation_samples,
                                                   base_state=self._state, **options)
        self._result, self._state = _copy(result), _copy(result["state"])
        self._training_report = _copy(result["report"])
        return result

    def infer(self, samples, **options):
        _require(not options, "codebase inference does not accept training or decoder options")
        _require(self._state is not None, "codebase inference requires a trained or loaded state")
        self._verify_adapter()
        result = features.infer_projection_features(self.contract, self._space, self._state, _codebase_targets(samples))
        return {**result, "feature_coverage_complete": all(row["unknown_atoms"] == 0 for row in result["coverage"]),
                "semantic_discrimination_guaranteed": False}

    def decode_formal_logic(self, *args, **kwargs):
        raise RuntimeVersionError("codebase_feature_v1 has no formula decoder or property prediction objective")

    def _register(self, registry, directory, result):
        self._verify_adapter()
        receipt = features.register_feature_candidate(registry, self.contract, self._space, result, directory,
                                                     parent_version_id=self._parent_version_id)
        self._state, self._training_report = _copy(result["state"]), _copy(result["report"])
        self._parent_version_id = receipt["version_id"]
        self._result = None
        return {**receipt, "runtime_id": self._descriptor["runtime_id"]}

    def register_candidate(self, registry, directory):
        _require(self._result is not None, "train a candidate before registering it")
        return self._register(registry, directory, self._result)

    def register_candidate_result(self, registry, directory, result):
        """Register a trusted isolated worker result without retraining it.

        The caller validates the worker envelope and current source/cohort. This
        method validates numerical/registry identity and preserves its metadata;
        accepting a result does not authenticate its numerical producer.
        """
        _require(self._result is None, "register the pending candidate before accepting a worker result")
        _require(type(result) is dict and set(result) == {"state", "report"}, "closed native feature result required")
        _require(len(features._raw(result)) <= MAX_CANDIDATE_BYTES, "worker feature result exceeds byte bound")
        result = _copy(result)
        _require(result["report"].get("base_state_sha256") ==
                 (None if self._state is None else features.digest(self._state)),
                 "worker result differs from the runtime numerical parent")
        return self._register(registry, directory, result)


class SourceBoundCodebaseFeatureRuntime(NativeRuntime):
    """Exact source-bound target feature basis, numerical state and ancestry.

    The target adapter and current-source coordinator own source custody. This
    runtime reconstructs structural features and has no semantic decoder,
    property predictor, proof authority, or model-head promotion operation.
    """
    def __init__(self, *, contract, feature_space, state=None, decoder_head=None):
        _require(type(contract) is ModalityContract and contract.domain == CODEBASE_DOMAIN,
                 "source-bound CodebaseIR runtime requires its exact modality contract")
        _require(contract.ir_schema == CODEBASE_SOURCE_FEATURE_SCHEMA,
                 "source-bound CodebaseIR target schema differs from this profile")
        _require(decoder_head is None, "source-bound CodebaseIR feature profile has no formal decoder")
        adapter, _ = _source_bound_codebase_adapter()
        _require(type(feature_space) is dict and type(feature_space.get("projection_ids")) is list
                 and bool(feature_space["projection_ids"])
                 and set(feature_space["projection_ids"]) <= {
                     adapter.CODEBASE_PROGRAM_PROJECTION, adapter.CODEBASE_CONTRACTS_PROJECTION},
                 "source-bound CodebaseIR feature basis contains an unsupported projection")
        super().__init__(CODEBASE_DOMAIN, contract=contract, feature_space=feature_space, state=state,
                         _runtime_version=CODEBASE_SOURCE_FEATURE_VERSION)
        self._training_report = None

    @property
    def training_report(self):
        return None if self._training_report is None else _copy(self._training_report)

    @property
    def parent_version_id(self):
        return self._parent_version_id

    def train(self, samples, *, validation_samples, **options):
        result = super().train(_source_bound_codebase_targets(samples),
                               validation_samples=_source_bound_codebase_targets(validation_samples), **options)
        self._training_report = _copy(result["report"])
        return result

    def infer(self, samples, **options):
        return super().infer(_source_bound_codebase_targets(samples), **options)

    def decode_formal_logic(self, *args, **kwargs):
        raise RuntimeVersionError("source-bound CodebaseIR feature profile has no formal decoder")


def _source_bound_codebase_targets(samples):
    from ...logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    adapter, _ = _source_bound_codebase_adapter()
    _require(type(samples) in (list, tuple) and 1 <= len(samples) <= 1024,
             "source-bound CodebaseIR target batch must be bounded and nonempty")
    return [adapter.validate_codebase_targets(sample if type(sample) is DomainTargetEnvelope
            else DomainTargetEnvelope.from_dict(sample)) for sample in samples]


class LegalRuntime:
    """Legal features with optional jointly trained latent formula projection/head."""
    def __init__(self, version, *, checkpoint=None, expected_sha256=None,
                 formula_checkpoint=None, formula_sha256=None, optimized=True, **model_options):
        _require(type(optimized) is bool, "optimized must be a boolean")
        self._optimized = optimized
        self._inference_session = None
        self._inference_decoder = None
        self._descriptor = describe_runtime("legal_ir", version)
        # The module name is selected solely from the closed local enum above.
        namespace = importlib.import_module(__package__ + ".autoencoder_lineages." + version)
        if checkpoint is None:
            _require(expected_sha256 is None, "checkpoint hash supplied without a checkpoint")
            self.model = namespace.Autoencoder(**model_options)
        else:
            self.model = namespace.load_checkpoint(checkpoint, expected_sha256=expected_sha256, **model_options)
        if formula_checkpoint is not None:
            if isinstance(formula_checkpoint, (str, Path)):
                self.model.load_formula_checkpoint(formula_checkpoint, expected_sha256=formula_sha256)
            else:
                _require(formula_sha256 is None, "in-memory formula checkpoint has no file hash")
                self.model.attach_formula_checkpoint(formula_checkpoint)
        else:
            _require(formula_sha256 is None, "formula hash supplied without checkpoint")

    def describe(self):
        result = {**_copy(self._descriptor), "model": self.model.describe()}
        if self.model._joint_formula_checkpoint is not None:
            result["formal_decoder"]["modes"].append("learned_latent")
            result["formal_decoder"]["learned_latent_head_attached"] = True
            result["formal_decoder"]["trained_neural_decoder"] = self.model._joint_formula_checkpoint["progress"]["optimizer_steps"] > 0
            result["formal_decoder"]["source_only"] = False
            result["objective_default"] = "formula_token_cross_entropy_plus_projected_embedding_mse"
        return result

    def train(self, samples, *, validation_samples=None, **options):
        self._inference_session = None
        self._inference_decoder = None
        return self.model.train_generalizable_projection(samples, validation_samples=validation_samples, **options)

    def infer(self, samples, **options):
        if self.model._joint_formula_checkpoint is not None:
            _require(not options, "joint formula inference has no bridge or compiler options")
            if self._optimized:
                from .modal_joint_formula_inference import JointInferenceSession
                # Explicit reattachment replaces the owning decoder after full
                # validation. In-place checkpoint/tensor writes still reach
                # the existing session's original integrity checks.
                decoder = self.model._joint_formula_decoder
                if (self._inference_session is None or self._inference_decoder is not decoder
                        or self._inference_session._model is not self.model):
                    session = JointInferenceSession(self.model)
                    self._inference_session = session
                    self._inference_decoder = decoder
                return self._inference_session.infer(samples)
            return self.model.decode_formal_logic(samples, mode="learned_latent")
        return self.model.evaluate(samples, **options)

    def decode_formal_logic(self, samples, *, mode=None, **options):
        if self._optimized and self.model._joint_formula_checkpoint is not None and (
                not mode or mode == "learned_latent"):
            _require(not options, "learned latent inference has no compiler or sampling options")
            return self.infer(samples)
        return self.model.decode_formal_logic(samples, mode=mode, **options)


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


class GroupedFormulaRuntime:
    """Opt-in inference over an exact local grouped-v2 checkpoint.

    Scope is a caller declaration, not an inferred legal interpretation. The
    strict owner restores model and optimizer state; this adapter exposes no
    training, candidate registration, migration, or numerical-vector input.
    """
    def __init__(self, *, checkpoint_path, checkpoint_sha256):
        _require(isinstance(checkpoint_path, (str, Path)), "grouped checkpoint requires a local path")
        _require(type(checkpoint_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", checkpoint_sha256),
                 "grouped checkpoint requires an exact SHA-256")
        path = Path(checkpoint_path)
        _require(path.is_file(), "grouped checkpoint file does not exist")
        with path.open("rb") as handle:
            raw = handle.read(100_000_001)
        _require(0 < len(raw) <= 100_000_000, "grouped checkpoint exceeds byte bound")
        _require(hashlib.sha256(raw).hexdigest() == checkpoint_sha256, "grouped checkpoint SHA-256 mismatch")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                _require(key not in result, "duplicate grouped checkpoint JSON key")
                result[key] = value
            return result

        def reject_constant(value):
            raise RuntimeVersionError("nonfinite grouped checkpoint JSON: " + value)

        checkpoint = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
        from ...logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as grouped
        model, _optimizer, steps = grouped.restore_grouped_span_checkpoint(checkpoint)
        self._model = model
        self._steps = steps
        self._checkpoint_sha256 = checkpoint_sha256
        self._checkpoint_seal = checkpoint["checkpoint_sha256"]
        self._producer = _copy(checkpoint["producer"])
        self._descriptor = describe_runtime("legal_ir", GROUPED_FORMULA_VERSION)

    def describe(self):
        return {**_copy(self._descriptor), "checkpoint_sha256": self._checkpoint_sha256,
                "checkpoint_content_sha256": self._checkpoint_seal,
                "checkpoint_producer": _copy(self._producer), "optimizer_steps": self._steps,
                "checkpoint_present": True, "trained_checkpoint_present": self._steps > 0}

    def infer(self, source_text, *, modal_scope=None):
        """Pass only raw source and a caller scope to the unchanged neural owner."""
        _require(type(source_text) is str, "grouped inference requires raw source_text")
        from ...logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as grouped
        result = grouped.predict_grouped_span_decoder(self._model, source_text, modal_scope)
        return {**result, "runtime_id": "legal_ir:" + GROUPED_FORMULA_VERSION,
                "checkpoint_sha256": self._checkpoint_sha256, "experimental": True,
                "source_conditioned": True, "latent_conditioned": False,
                "requires_validation": True, "accepted": False, "kernel_checked": False,
                "lake_executed": False, **features.FALSE}

    def decode_formal_logic(self, source_text, *, modal_scope=None):
        """Render only an emitted closed request; preserve neural refusals."""
        result = self.infer(source_text, modal_scope=modal_scope)
        formal = None
        if result["request"] is not None:
            from ...logic.deontic.coordination_decoder import CoordinationDecodeRequest, decode_coordination_request
            formal = decode_coordination_request(CoordinationDecodeRequest.from_dict(result["request"]))
        return {**result, "formal_output": formal, "formula_count": int(formal is not None),
                "decoded_formulas_generated": formal is not None,
                "blockers": result["blockers"] + ([] if formal is None else formal["blockers"])}


class NativeFormulaRuntime:
    """Separate categorical decoder training, exact resume and inference paths.

    Inputs are typed compiler projections. Reconstructed records are learned;
    this runtime does not independently translate raw text to logic.
    """
    def __init__(self, domain, *, checkpoint, expected_sha256=None):
        from . import native_formula_training as learning
        _require(domain in NATIVE_DOMAINS, "unknown native domain")
        if isinstance(checkpoint, (str, Path)):
            self._checkpoint = learning.load_checkpoint(checkpoint, expected_sha256=expected_sha256)
        else:
            _require(expected_sha256 is None, "in-memory checkpoints do not accept a file hash")
            learning.validate_checkpoint(checkpoint)
            self._checkpoint = _copy(checkpoint)
        _require(self._checkpoint["domain_id"] == domain, "checkpoint belongs to another domain")
        self._domain, self._result, self._parent_version_id = domain, None, None

    @property
    def checkpoint(self):
        return _copy(self._checkpoint)

    def describe(self):
        from . import native_formula_training as learning
        return {**describe_runtime(self._domain, NATIVE_FORMULA_VERSION),
            "checkpoint_sha256": learning.checkpoint_digest(self._checkpoint),
            "parent_version_id": self._parent_version_id, "checkpoint_present": True,
            "trained_checkpoint_present": self._checkpoint["latest"]["progress"]["optimizer_steps"] > 0}

    def train(self, samples, *, validation_samples, **options):
        from . import native_formula_training as learning
        _require(self._result is None, "register the pending candidate before training another version")
        _require("checkpoint" not in options, "resume checkpoint is bound to this runtime")
        result = learning.train_native_formula(self._checkpoint, samples, validation_samples, **options)
        # A deadline-only observation must not strand a runtime behind a
        # pending candidate which has no optimizer update to register.
        if result["report"]["training_executed"]:
            self._checkpoint, self._result = _copy(result["checkpoint"]), _copy(result)
        return result

    def decode_formal_logic(self, samples, *, mode="learned_fields", selected=True):
        from . import native_formula_training as learning
        _require(mode == "learned_fields", "native formula runtime supports only learned_fields mode")
        return learning.infer_native_formula(self._checkpoint, samples, selected=selected)

    def infer(self, samples, *, selected=True):
        return self.decode_formal_logic(samples, selected=selected)

    def register_candidate(self, registry, directory):
        from .native_formula_checkpoint import register_candidate
        _require(self._result is not None, "train a candidate before registering it")
        result = register_candidate(registry, self._result, directory, parent_version_id=self._parent_version_id)
        self._parent_version_id, self._result = result["version_id"], None
        return {**result, "runtime_id": self._domain + ":" + NATIVE_FORMULA_VERSION}


def build_native_formula_runtime(domain, training_targets, *, validation_samples, projection_ids,
                                 latent_width=16, learning_rate=.01, batch_size=8, seed=1729):
    """Create a new explicit formula lineage; never migrate historical weights."""
    from .native_formula_training import build_native_formula_checkpoint
    checkpoint = build_native_formula_checkpoint(domain, training_targets, validation_samples,
        projection_ids=projection_ids, latent_width=latent_width, learning_rate=learning_rate,
        batch_size=batch_size, seed=seed)
    return NativeFormulaRuntime(domain, checkpoint=checkpoint)


def open_runtime(domain, version, **binding):
    """Select explicitly. Dimensions, source metadata, and filenames never dispatch."""
    descriptor = describe_runtime(domain, version)
    _require(descriptor["integrated"], descriptor.get("unsupported_reason", "runtime is not integrated"))
    if domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION:
        return SourceBoundCodebaseFeatureRuntime(**binding)
    if domain == CODEBASE_DOMAIN:
        return CodebaseFeatureRuntime(**binding)
    if version == PUBLISHED_384_VERSION:
        from ...logic.formalization.autoencoder.checkpoint_hub import open_autoencoder
        return open_autoencoder(domain, **binding)
    if domain in NATIVE_DOMAINS and version == NATIVE_FORMULA_VERSION:
        return NativeFormulaRuntime(domain, **binding)
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        return LearnedFormulaRuntime(**binding)
    if domain == "legal_ir" and version == GROUPED_FORMULA_VERSION:
        return GroupedFormulaRuntime(**binding)
    if domain == "legal_ir":
        return LegalRuntime(version, **binding)
    return NativeRuntime(domain, **binding)


def build_native_runtime(domain, version, training_targets, *, projection_ids, ir_schema, latent_width=4,
                         with_formal_decoder=True):
    """Build a v1 basis from training only; excluded native views remain recorded."""
    descriptor = describe_runtime(domain, version)
    _require(domain in NATIVE_DOMAINS and version == "native_v1",
             "this builder requires native_v1; use build_native_formula_runtime for decoder training")
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


def build_codebase_feature_runtime(training_targets, *, latent_width=8):
    """Fit only the captured training vocabulary; no fitting or head promotion."""
    adapter, _ = _target_adapter(CODEBASE_DOMAIN)
    targets = _codebase_targets(training_targets)
    space = features.build_feature_space(CODEBASE_DOMAIN, [adapter.PROJECTION_ID], targets)
    contract = features.build_native_feature_contract(space, ir_schema=adapter.TARGET_PROFILE,
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(), latent_width=latent_width)
    return open_runtime(CODEBASE_DOMAIN, CODEBASE_FEATURE_VERSION, contract=contract, feature_space=space)


def build_source_bound_codebase_runtime(training_targets, *, projection_ids=None, latent_width=8):
    """Fit the explicit source-bound CodebaseIR feature basis on training only."""
    adapter, _ = _source_bound_codebase_adapter()
    targets = _source_bound_codebase_targets(training_targets)
    if projection_ids is None:
        projection_ids = [adapter.CODEBASE_PROGRAM_PROJECTION, adapter.CODEBASE_CONTRACTS_PROJECTION]
    space = features.build_feature_space(CODEBASE_DOMAIN, projection_ids, targets)
    contract = features.build_native_feature_contract(space, ir_schema=CODEBASE_SOURCE_FEATURE_SCHEMA,
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(), latent_width=latent_width)
    return open_runtime(CODEBASE_DOMAIN, CODEBASE_SOURCE_FEATURE_VERSION, contract=contract, feature_space=space)


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


def _source_bound_completed_run_metadata(registry, row, saved, contract):
    """Replay native durable run linkage and bind its result to this checkpoint."""
    metadata = row["metadata"]
    _require(type(metadata) is dict and set(metadata) == {"producer_run", "attempt", "result"}
             and type(metadata["producer_run"]) is str
             and type(metadata["attempt"]) is int and metadata["attempt"] >= 1,
             "source-bound completed-run candidate metadata differs")
    result = metadata["result"]
    expected = {"training_purpose": "feature_pretraining", "contract_sha256": contract.sha256,
                "feature_space_sha256": features.digest(saved["feature_space"]),
                "state_sha256": features.digest(saved["state"]),
                "report_sha256": features.digest(saved["report"]), **features.FALSE}
    _require(type(result) is dict and result == expected
             and all(result.get(name) is False for name in features.FALSE),
             "source-bound completed-run result identity or authority differs")
    completion = registry.get_run_completion(metadata["producer_run"])
    _require(type(completion) is dict and set(completion) == {"run", "completion_receipt", "candidate_version"},
             "source-bound candidate lacks a native completed run")
    receipt, run = completion["completion_receipt"], completion["run"]
    _require(completion["candidate_version"] == row and type(receipt) is dict and type(run) is dict
             and receipt.get("version_id") == row["version_id"]
             and receipt.get("run_id") == metadata["producer_run"]
             and receipt.get("admitted") is False and receipt.get("promoted") is False
             and run.get("run_id") == metadata["producer_run"]
             and run.get("attempt") == metadata["attempt"] and run.get("result") == result
             and run.get("variant_id") == row["variant_id"]
             and run.get("base_version_id") == row["parent_version_id"],
             "source-bound completed-run producer binding differs")


def load_version(registry, version_id, *, domain, version):
    """Verify and reload a native candidate from the existing DuckDB registry.

    The caller selects the expected domain/version. Metadata cannot select
    imports, replace projections, migrate Adam state, or raise authority.
    Only the source-bound CodebaseIR feature profile additionally accepts
    candidates tied to an independently replayed native completed-run record.
    """
    descriptor = describe_runtime(domain, version)
    _require("load_version" in descriptor["capabilities"], "runtime lacks registry load_version")
    if domain == "legal_ir" and version == LEARNED_FORMULA_VERSION:
        from .legal_formula_checkpoint import load_registered_candidate
        saved = load_registered_candidate(registry, version_id)
        runtime = LearnedFormulaRuntime(checkpoint=saved["checkpoint"])
        runtime._parent_version_id = version_id
        return runtime
    if domain in NATIVE_DOMAINS and version == NATIVE_FORMULA_VERSION:
        from .native_formula_checkpoint import load_registered_candidate
        saved = load_registered_candidate(registry, version_id)
        runtime = NativeFormulaRuntime(domain, checkpoint=saved["checkpoint"])
        runtime._parent_version_id = version_id
        return runtime
    row = registry.get_version(version_id)
    if "decoder_head_sha256" in row["metadata"]:
        _require(domain != CODEBASE_DOMAIN, "codebase feature runtime does not accept formal decoder artifacts")
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
    feature_metadata = {"contract_sha256": contract.sha256,
                        "training_purpose": "feature_pretraining", **features.FALSE}
    if row["metadata"] != feature_metadata or (
            domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION
            and any(row["metadata"].get(name) is not False for name in features.FALSE)):
        _require(domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION,
                 "candidate metadata differs")
        _source_bound_completed_run_metadata(registry, row, saved, contract)
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
    if domain == CODEBASE_DOMAIN:
        runtime._training_report = _copy(report)
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
    _require(not (domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION),
             "source-bound CodebaseIR feature profile has no formal decoder")
    _require(domain != CODEBASE_DOMAIN, "codebase_feature_v1 has no formal decoder")
    if domain in NATIVE_DOMAINS and version == "native_v2":
        return StreamedFormalRuntime(domain, **binding)
    return open_runtime(domain, version, **binding)


__all__ = ["RuntimeVersionError", "list_runtimes", "describe_runtime", "prepare_targets",
           "open_runtime", "build_native_runtime", "load_version", "open_formal_decoder",
           "NativeRuntime", "LegalRuntime", "StreamedFormalRuntime", "LearnedFormulaRuntime",
           "LEARNED_FORMULA_VERSION", "NATIVE_FORMULA_VERSION", "NativeFormulaRuntime",
           "GROUPED_FORMULA_VERSION", "GroupedFormulaRuntime",
           "build_native_formula_runtime", "CodebaseFeatureRuntime", "build_codebase_feature_runtime",
           "CODEBASE_DOMAIN", "CODEBASE_FEATURE_VERSION", "CODEBASE_SOURCE_FEATURE_VERSION",
           "CODEBASE_SOURCE_FEATURE_SCHEMA", "SourceBoundCodebaseFeatureRuntime",
           "build_source_bound_codebase_runtime"]

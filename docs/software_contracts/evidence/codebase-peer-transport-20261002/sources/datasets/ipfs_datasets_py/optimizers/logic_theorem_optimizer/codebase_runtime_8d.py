"""Explicit source-bound 8D feature runtime over existing shared numerics.

Ported from the reviewed source-bound runtime; legal/native/384D dispatch and
its producer bytes remain unchanged. This profile has no formal decoder and
never promotes a model or turns reconstruction into checked semantics.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from . import autoencoder_projection_features as features
from .autoencoder_modality_contracts import ModalityAdapterRegistry, ModalityContract
SCHEMA = "autoencoder-runtime-interface/v1"
CODEBASE_DOMAIN = "codebase_ir"
CODEBASE_SOURCE_FEATURE_VERSION = "source_bound_feature_v1"
CODEBASE_SOURCE_FEATURE_SCHEMA = "codebase-ir-source-bound-feature-targets@1"
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


def _source_bound_codebase_adapter():
    from ...logic.software_contracts import codebase_ir_targets
    return codebase_ir_targets, codebase_ir_targets.prepare_codebase_targets


def prepare_targets(domain, version, **inputs):
    """Delegate source custody to the exact native captured-source adapter."""
    describe_runtime(domain, version)
    return _source_bound_codebase_adapter()[1](**inputs)


def describe_runtime(domain, version):
    _require(domain == CODEBASE_DOMAIN and version == CODEBASE_SOURCE_FEATURE_VERSION, "explicit source-bound8D runtime required")
    root = _optimizer_root()
    adapter, _ = _source_bound_codebase_adapter()
    paths = [("codebase_runtime_8d.py", Path(__file__)),
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
            "qualification_requirements": adapter.describe_codebase_target_profile(),
            "source_custody_owner": "native_codebase_target_adapter_and_training_coordinator",
            "runtime_behavior_proved": False, "kernel_checked": False,
            "planner_admission_eligible": False, "cache_authoritative": False,
            "source_identity": _source_identity(paths), **features.FALSE}


class _NativeAdapter:
    def __init__(self, contract, space):
        self.contract, self.space = contract, _copy(space)

    def train(self, samples, validation_samples, **options):
        return features.train_projection_features(self.contract, self.space, samples,
                                                  validation_samples, **options)

    def evaluate(self, state, samples):
        return features.infer_projection_features(self.contract, self.space, state, samples)


class _SourceRuntime:
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
        _require(decoder_head is None, "source-bound feature runtime has no formal decoder")
        self._decoder_head = None

    def _verify_adapter(self):
        contract = self.contract
        domain = contract.domain
        adapter, _ = _source_bound_codebase_adapter()
        _require(contract.adapter.sha256 == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
                 "installed native target adapter differs from contract")

    def describe(self):
        variant_id = self.contract.variant_id
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
        if self._parent_version_id is not None:
            parent = registry.get_version(self._parent_version_id)
            registry.verify_artifact(parent["artifact"])
        result = features.register_feature_candidate(registry, self.contract, self._space, self._result,
            directory, parent_version_id=self._parent_version_id)
        self._parent_version_id = result["version_id"]
        self._result = None
        return {**result, "runtime_id": self._descriptor["runtime_id"]}

    def decode_formal_logic(self, *args, **kwargs):
        raise RuntimeVersionError("source-bound CodebaseIR feature profile has no formal decoder")



class SourceBoundCodebaseFeatureRuntime(_SourceRuntime):
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


def open_runtime(domain, version, **binding):
    describe_runtime(domain, version)
    return SourceBoundCodebaseFeatureRuntime(**binding)


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
    describe_runtime(domain, version)
    row = registry.get_version(version_id)
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

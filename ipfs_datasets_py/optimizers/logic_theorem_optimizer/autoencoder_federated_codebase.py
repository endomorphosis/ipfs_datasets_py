"""Exact-base 8D CodebaseIR feature parameter federation.

The source/model owner verifies the base artifact, native version, approved
corpora and actual local optimizer work. This adapter snapshots compatible
numerical state and uses the existing FedAvg/update protocol. It opens no
registry, writes no artifact, downloads nothing and confers no proof authority.
Aggregates deliberately start a new optimizer history with zero Adam moments.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from . import autoencoder_federated as federation
from . import autoencoder_projection_features as features
from . import autoencoder_runtime_registry as runtimes
from .autoencoder_modality_contracts import ModalityContract


PROFILE = "codebase-source-feature-float64@1"
RUNTIME_PROFILE = "codebase_ir/" + runtimes.CODEBASE_SOURCE_FEATURE_VERSION
OPTIMIZER_POLICY = "aggregate_fresh_adam_zero_moments_and_progress@1"
SCHEMA = "codebase-federated-feature-base@1"
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
_NAMES = ("encoder.weight", "encoder.bias", "decoder.weight", "decoder.bias")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value, name):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             name + " must be an exact lowercase SHA256 digest")
    return value


def _version(value):
    _require(type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None,
             "base_version_id must be an exact native sha256 version identity")
    return value


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _state_parameters(state, feature_count):
    shapes = ((feature_count, 8), (8,), (8, feature_count), (feature_count,))
    specs = tuple(sorted((federation.ParameterSpec(name, shape, "float64")
                          for name, shape in zip(_NAMES, shapes)), key=lambda spec: spec.name))
    values = {}
    for name, shape, array in zip(_NAMES, shapes, state["parameters"]):
        values[name] = [float(value) for row in array for value in row] if len(shape) == 2 else [float(value) for value in array]
    # The generic binary commitment also validates names, lengths, finite
    # builtin numbers and exact dtype semantics, preserving signed zero.
    federation.parameter_digest(specs, values)
    return specs, values


def _reshape(values, shape):
    if len(shape) == 1:
        return list(values)
    return [list(values[index * shape[1]:(index + 1) * shape[1]]) for index in range(shape[0])]


def _validate_snapshot(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_CHECKPOINT_BYTES,
             "bounded immutable CodebaseIR base bytes required")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid CodebaseIR base JSON") from exc
    _require(type(value) is dict and set(value) == {"schema", "contract", "feature_space", "state"}
             and value["schema"] == SCHEMA and _wire(value) == raw,
             "closed canonical CodebaseIR base snapshot required")
    contract = ModalityContract.from_dict(value["contract"])
    _require(contract.domain == "codebase_ir" and contract.ir_schema == runtimes.CODEBASE_SOURCE_FEATURE_SCHEMA
             and contract.state_codec.version == "1:latent-8", "federation requires the exact source-bound 8D feature profile")
    # This constructor revalidates installed adapter/numerical identities and
    # the frozen basis/state without running inference or training.
    runtime = runtimes.open_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        contract=contract, feature_space=value["feature_space"], state=value["state"])
    _require(type(runtime) is runtimes.SourceBoundCodebaseFeatureRuntime,
             "exact source-bound native runtime required")
    _require(runtime.state["latent_width"] == 8, "CodebaseIR federated latent width must be 8")
    _state_parameters(runtime.state, len(runtime.feature_space["columns"]))
    return value


@dataclass(frozen=True, slots=True)
class CodebaseFeatureCheckpoint:
    """Owned immutable numerical snapshot and owner-supplied base references.

    Digest syntax and numerical compatibility are checked here. Independent
    artifact-byte/native-version verification belongs to the source owner;
    these references alone are neither provenance nor execution attestation.
    """
    _snapshot_json: bytes
    base_sha256: str
    base_version_id: str

    def __post_init__(self):
        _require(type(self) is CodebaseFeatureCheckpoint, "exact CodebaseFeatureCheckpoint required")
        _sha(self.base_sha256, "base_sha256")
        _version(self.base_version_id)
        _validate_snapshot(self._snapshot_json)

    @classmethod
    def from_runtime(cls, runtime, *, base_sha256, base_version_id):
        _require(type(runtime) is runtimes.SourceBoundCodebaseFeatureRuntime,
                 "exact SourceBoundCodebaseFeatureRuntime required")
        _require(runtime.state is not None, "trained or loaded source-bound state required")
        if runtime.parent_version_id is not None:
            _require(runtime.parent_version_id == base_version_id, "runtime native base version differs")
        snapshot = {"schema": SCHEMA, "contract": runtime.contract.to_dict(),
                    "feature_space": runtime.feature_space, "state": runtime.state}
        return cls(_wire(snapshot), base_sha256, base_version_id)

    def _checked(self):
        # Reconstruct even frozen values to reject unsafe object mutation.
        _require(type(self) is CodebaseFeatureCheckpoint, "exact CodebaseFeatureCheckpoint required")
        return CodebaseFeatureCheckpoint(self._snapshot_json, self.base_sha256, self.base_version_id)

    @property
    def contract(self):
        return ModalityContract.from_dict(json.loads(self._snapshot_json)["contract"])

    @property
    def feature_space(self):
        return json.loads(self._snapshot_json)["feature_space"]

    @property
    def state(self):
        return json.loads(self._snapshot_json)["state"]

    @property
    def parameter_specs(self):
        return _state_parameters(self.state, len(self.feature_space["columns"]))[0]

    @property
    def parameters(self):
        return _state_parameters(self.state, len(self.feature_space["columns"]))[1]

    @property
    def base_parameters_sha256(self):
        return federation.parameter_digest(self.parameter_specs, self.parameters)

    @property
    def semantic_profile(self):
        return {"profile": PROFILE, "runtime_profile": RUNTIME_PROFILE,
                "latent_width": 8, "dtype": "float64", "input": "native_source_bound_structural_features",
                "contract": self.contract.to_dict(), "feature_space": self.feature_space,
                "tuning_targets_sha256": self.state["tuning_targets_sha256"],
                "optimizer_config": self.state["optimizer_config"],
                "aggregate_optimizer_policy": OPTIMIZER_POLICY,
                "semantic_decoder": False, "proof_authority": False}

    @property
    def embedding_producer_sha256(self):
        # This commits the actual structural feature producer/basis/objective;
        # there is no text embedding producer or implicit GTE selection.
        return features.digest(self.semantic_profile)

    def build_round(self, round_id, lineage_id, clients, max_local_steps=1):
        base = self._checked()
        return federation.FederatedRound(round_id=round_id, model_id=base.contract.variant_id,
            lineage_id=lineage_id, dimension=8, architecture=PROFILE, runtime_profile=RUNTIME_PROFILE,
            base_sha256=base.base_sha256, base_parameters_sha256=base.base_parameters_sha256,
            embedding_producer_sha256=base.embedding_producer_sha256,
            parameters=base.parameter_specs, clients=clients, max_local_steps=max_local_steps)

    def validate_round(self, round_spec):
        base = self._checked()
        _require(type(round_spec) is federation.FederatedRound, "native FederatedRound required")
        checked = federation.FederatedRound(**{name: getattr(round_spec, name)
                                             for name in round_spec.__dataclass_fields__})
        _require(checked.model_id == base.contract.variant_id and checked.dimension == 8
            and checked.architecture == PROFILE and checked.runtime_profile == RUNTIME_PROFILE
            and checked.base_sha256 == base.base_sha256
            and checked.base_parameters_sha256 == base.base_parameters_sha256
            and checked.embedding_producer_sha256 == base.embedding_producer_sha256
            and checked.parameters == base.parameter_specs,
            "round belongs to another CodebaseIR base, feature semantics or layout")
        return checked

    def build_update(self, round_spec, client_id, trained_state, local_steps):
        """Snapshot selected-state deltas with bounded declared optimizer work.

        The owner binds ``local_steps`` to actual attempted optimizer steps.
        Native tuning may select an earlier state, including the unchanged
        parent; that valid rollback produces a zero delta, not invented work.
        """
        base = self._checked()
        round_spec = base.validate_round(round_spec)
        _require(type(local_steps) is int and 0 < local_steps <= round_spec.max_local_steps,
                 "actual declared local_steps must fit the positive round bound")
        _require(type(trained_state) is dict and len(_wire(trained_state)) <= MAX_CHECKPOINT_BYTES,
                 "bounded native trained state required")
        state = json.loads(_wire(trained_state))
        features._validate_state(base.contract, base.feature_space, state)
        initial = base.state
        _require(state["tuning_targets_sha256"] == initial["tuning_targets_sha256"]
            and state["optimizer_config"] == initial["optimizer_config"]
            and initial["completed_epochs"] <= state["completed_epochs"] <= initial["completed_epochs"] + local_steps,
            "local selected state changed fixed tuning, optimizer policy or progress")
        _, final = _state_parameters(state, len(base.feature_space["columns"]))
        old = base.parameters
        deltas = {name: [value - previous for value, previous in zip(values, old[name])]
                  for name, values in final.items()}
        client = next((item for item in round_spec.clients if item.client_id == client_id), None)
        _require(client is not None, "client is not approved for this CodebaseIR round")
        return federation.make_client_update(round_spec, client_id, deltas, local_steps=local_steps,
                                               local_data_sha256=client.local_data_sha256)

    def materialize_state(self, round_spec, candidate):
        """Return aggregate weights with fresh zero Adam history, never promote."""
        base = self._checked()
        round_spec = base.validate_round(round_spec)
        _require(type(candidate) is federation.AggregateCandidate, "native AggregateCandidate required")
        checked = federation.AggregateCandidate(candidate._parameter_rows, candidate._provenance_json,
                                                 candidate.candidate_sha256)
        _require(checked.provenance["round"] == round_spec.manifest
                 and checked.provenance["round_sha256"] == round_spec.round_sha256,
                 "aggregate belongs to another complete CodebaseIR round")
        state = base.state
        feature_count = len(base.feature_space["columns"])
        shapes = ((feature_count, 8), (8,), (8, feature_count), (feature_count,))
        parameters = checked.parameters
        state["parameters"] = [_reshape(parameters[name], shape) for name, shape in zip(_NAMES, shapes)]
        state["adam"] = [{"step": 0, "exp_avg": _reshape([0.0] * spec.size, spec.shape),
                          "exp_avg_sq": _reshape([0.0] * spec.size, spec.shape)}
                         for spec in (federation.ParameterSpec(name, shape, "float64")
                                      for name, shape in zip(_NAMES, shapes))]
        state["completed_epochs"] = 0
        features._validate_state(base.contract, base.feature_space, state)
        _require(federation.parameter_digest(base.parameter_specs,
            _state_parameters(state, feature_count)[1]) == checked.provenance["parameters_sha256"],
            "aggregate materialization changed parameter layout or values")
        return state


def describe_profile():
    return {"profile": PROFILE, "runtime_profile": RUNTIME_PROFILE, "dimension": 8,
            "dtype": "float64", "parameter_names": list(_NAMES), "algorithm": federation.ALGORITHM,
            "aggregate_optimizer_policy": OPTIMIZER_POLICY, "registry_writes": False,
            "artifact_writes": False, "semantic_decoder": False, "proof_authority": False,
            "qualified": False, "admitted": False, "promotion_performed": False}


__all__ = ["CodebaseFeatureCheckpoint", "describe_profile", "PROFILE", "RUNTIME_PROFILE", "OPTIMIZER_POLICY"]

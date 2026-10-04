"""Explicit FedAvg branches for the published current384D learned formula head.

The sparse core, target vocabulary, configuration, and pinned implementation
remain fixed. Each client starts a fresh local optimizer on its own committed
corpus. An averaged head is a provisional, separate artifact, never a fabricated
historical resume checkpoint. At least one actual owner training step is needed
to finalize it into the existing v1 checkpoint/package format.

Imports perform no training, file access, database access, or network access.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat

from .autoencoder_federated import (
    AggregateCandidate, ClientSpec, FederatedRound, ParameterSpec,
    aggregate_round, make_client_update, parameter_digest,
)


PROFILE = "modal-latent-formula-fedavg/v1"
CANDIDATE_SCHEMA = "modal-latent-formula-federated-candidate/v1"
BRANCH_SCHEMA = "modal-latent-formula-federated-local-branch/v1"
FINALIZATION_SCHEMA = "modal-latent-formula-federated-owner-finalization/v1"
MAX_BYTES = 96 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "proof_authority": False, "semantic_correctness_verified": False,
          "promotion_performed": False, "publication_performed": False,
          "lake_executed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _owned(value):
    return json.loads(_raw(value))


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None,
             label + " requires lowercase SHA256")


def _parse(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "bounded immutable JSON bytes required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    _require(type(value) is dict and _raw(value) == raw, "canonical finite JSON object required")
    return value


def _cpu():
    # Use the same process lock/thread restoration as the existing 384D package.
    from .domain_384_autoencoder import _cpu as allocated_cpu
    return allocated_cpu()


def _learning():
    from . import modal_latent_formula
    return modal_latent_formula


def _source_profile():
    from . import autoencoder_federated
    learning = _learning()
    return {"schema": "modal-latent-formula-federation-sources/v1",
            "formula_implementation": learning._implementation(),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "reducer_sha256": hashlib.sha256(Path(autoencoder_federated.__file__).read_bytes()).hexdigest()}


def _package_module():
    from ...logic.formalization.autoencoder import legal_384_package
    return legal_384_package


def _head_from_artifact(raw, kind):
    value = _parse(raw)
    learning = _learning()
    if kind == "legal384_package":
        package = _package_module()
        runtime = package.Runtime(value)
        fixture = value["fixture"]
        _require(type(fixture) is dict and set(fixture) == {"rows", "expected_result_sha256"},
                 "complete verified Legal package fixture required")
        _require(_digest(runtime.infer(fixture["rows"])["result"]) == fixture["expected_result_sha256"],
                 "Legal package inference fixture differs")
        head = value["formula_checkpoint"]
        contract = value["embedding_contract"]
    else:
        _require(kind == "formula_head", "unsupported parent artifact kind")
        head, contract = value, None
    _require(type(head) is dict, "a learned formula head is required")
    learning.validate_checkpoint(head)
    _require(head["binding"]["lineage_id"] == "current_legal_v2"
             and head["binding"]["dimension"] == 384,
             "this federation profile supports current384D formula heads only")
    _require(head["progress"]["optimizer_steps"] > 0,
             "a genuinely trained parent formula head is required")
    return head, contract


@dataclass(frozen=True, slots=True)
class VerifiedFormulaBase:
    """Owned full parent bytes; SHA verification does not prove model quality."""

    _artifact_bytes: bytes
    base_sha256: str
    kind: str

    def __post_init__(self):
        _sha(self.base_sha256, "base_sha256")
        _require(type(self._artifact_bytes) is bytes
                 and hashlib.sha256(self._artifact_bytes).hexdigest() == self.base_sha256,
                 "parent artifact SHA256 differs")
        with _cpu():
            _head_from_artifact(self._artifact_bytes, self.kind)

    @property
    def head(self):
        value = _parse(self._artifact_bytes)
        return value["formula_checkpoint"] if self.kind == "legal384_package" else value

    @property
    def head_sha256(self):
        return _digest(self.head)

    @property
    def package_payload(self):
        return _parse(self._artifact_bytes) if self.kind == "legal384_package" else None

    @property
    def embedding_producer_sha256(self):
        """Package's explicit embedding-contract commitment, or None for a head."""
        payload = self.package_payload
        return None if payload is None else formula_embedding_digest(payload["embedding_contract"])


def _base(base):
    _require(type(base) is VerifiedFormulaBase, "VerifiedFormulaBase required")
    return VerifiedFormulaBase(base._artifact_bytes, base.base_sha256, base.kind)


def _read(path, expected_sha256):
    _sha(expected_sha256, "expected_sha256")
    source = Path(path)
    info = source.stat()
    _require(not source.is_symlink() and stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BYTES,
             "bounded regular parent artifact required")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256,
             "parent artifact SHA256 differs")
    return raw


def load_formula_base(path, *, expected_sha256):
    """Verify canonical standalone current384D v1 head bytes and source pins."""
    return VerifiedFormulaBase(_read(path, expected_sha256), expected_sha256, "formula_head")


def load_legal384_formula_base(path, *, expected_sha256):
    """Verify the complete released package, source/core binding and fixture."""
    raw = _read(path, expected_sha256)
    with _cpu():
        _package_module().load_package(path, expected_sha256=expected_sha256)
    return VerifiedFormulaBase(raw, expected_sha256, "legal384_package")


def formula_embedding_digest(contract):
    return _digest({"schema": "modal-latent-formula-embedding-contract/v1", "contract": contract})


def prepare_legal384_formula_rows(base, rows, *, expected_embedding_producer_sha256):
    """Derive owned local training rows from a package's exact frozen core.

    Incoming rows contain exactly id/source_text/embedding/canonical_ir. Supplied
    embeddings must come from the owner-approved producer; this verifies its
    declared contract identity and recomputes latents rather than accepting
    caller-supplied ones. The existing target vocabulary remains fixed.
    """
    base = _base(base)
    _require(base.kind == "legal384_package", "row derivation requires a complete verified Legal package")
    _require(expected_embedding_producer_sha256 == base.embedding_producer_sha256,
             "embedding producer differs from the verified package")
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128,
             "one to 128 formula source rows required")
    _require(all(type(row) is dict and set(row) == {"id", "source_text", "embedding", "canonical_ir"}
                 for row in rows), "closed id/source_text/embedding/canonical_ir rows required")
    with _cpu():
        package = _package_module()
        from . import modal_joint_formula as joint
        payload = base.package_payload
        runtime = package.Runtime(payload)
        inputs = [{name: row[name] for name in ("id", "source_text", "embedding")} for row in rows]
        targets = [{name: row[name] for name in ("id", "source_text", "canonical_ir")} for row in rows]
        samples = package._rows(inputs, payload["embedding_contract"])
        derived = joint._rows(runtime.model, samples, targets)
        _require(joint._core_binding(runtime.model) == payload["core_binding"],
                 "core changed during formula row derivation")
        training, _ = _rows(derived, [], base.head)
        return training


def _flatten(value):
    if type(value) is list:
        return tuple(number for nested in value for number in _flatten(nested))
    _require(type(value) in (int, float), "builtin finite tensor values required")
    return (float(value),)


def _parameters(head):
    learning = _learning()
    model = learning._model(head["binding"], head["codec"], head["config"])
    templates = model.state_dict()
    _require(set(head["model_state"]) == set(templates), "formula parameter names differ")
    specs, values = [], {}
    for name, tensor in sorted(templates.items()):
        typed = learning._tensor(head["model_state"][name], tensor, name)
        specs.append(ParameterSpec(name, tuple(tensor.shape), "float32"))
        # The historical loader accepts JSON doubles that round to float32.
        # Deltas must use the tensors training actually loads as their basis.
        values[name] = typed.reshape(-1).tolist()
    return tuple(specs), values


def _reshape(values, shape):
    iterator = iter(values)
    def read(dimensions):
        return [read(dimensions[1:]) for _ in range(dimensions[0])] if dimensions else next(iterator)
    result = read(shape)
    _require(next(iterator, None) is None, "formula parameter shape differs")
    return result


def _model_state(specs, parameters):
    return {spec.name: _reshape(parameters[spec.name], spec.shape) for spec in specs}


def _architecture(base, specs):
    head = base.head
    payload = base.package_payload
    return _learning().ARCHITECTURE + "/" + _digest({
        "binding": head["binding"], "config": head["config"], "codec": head["codec"],
        "implementation": head["implementation"], "projection_id": head["projection_id"],
        "parameters": [spec.manifest for spec in specs], "sources": _source_profile(),
        "embedding_contract": None if payload is None else payload["embedding_contract"]})


def create_formula_round(base, *, round_id, model_id, clients, embedding_producer_sha256,
                         max_local_steps=1):
    """Bind fixed core/config/vocabulary/parameters and owner-approved clients."""
    base = _base(base)
    with _cpu():
        specs, parameters = _parameters(base.head)
        if base.embedding_producer_sha256 is not None:
            _require(embedding_producer_sha256 == base.embedding_producer_sha256,
                     "embedding producer differs from the verified package")
        return FederatedRound(round_id, model_id, "current_legal_v2", 384,
            _architecture(base, specs), PROFILE, base.base_sha256,
            parameter_digest(specs, parameters), embedding_producer_sha256,
            specs, clients, max_local_steps)


def _round(base, round_spec):
    _require(type(round_spec) is FederatedRound, "FederatedRound required")
    expected = create_formula_round(base, round_id=round_spec.round_id, model_id=round_spec.model_id,
        clients=round_spec.clients, embedding_producer_sha256=round_spec.embedding_producer_sha256,
        max_local_steps=round_spec.max_local_steps)
    _require(round_spec.manifest == expected.manifest, "formula round core, source, corpus layout or base differs")
    return expected


def _rows(training_rows, tuning_rows, head):
    """Validate owner-supplied core-derived rows, then take an owned snapshot."""
    learning = _learning()
    learning._splits(training_rows, tuning_rows, 384)
    owned = _owned({"training": training_rows, "tuning": tuning_rows})
    training, tuning = learning._splits(owned["training"], owned["tuning"], 384)
    for row in training + tuning:
        learning.codec_module.encode_target(head["codec"], row["canonical_ir"])
    return training, tuning


def formula_local_data_digest(training_rows, tuning_rows):
    """Commit complete local training/tuning rows, including core-derived latents.

    The caller must verify latents against the bound core and authenticate its
    embedding producer before approving this digest. A hash alone proves neither.
    """
    with _cpu():
        learning = _learning()
        training, tuning = learning._splits(training_rows, tuning_rows, 384)
        return _digest({"schema": "modal-latent-formula-local-data/v1",
                        "training": training, "tuning": tuning})


def _local_branch(head, training, tuning, parent_sha256):
    learning = _learning()
    branch = _owned(head)
    branch.update(training_manifest_sha256=learning.checkpoint_digest(training),
        tuning_manifest_sha256=learning.checkpoint_digest(tuning),
        training_count=len(training), tuning_count=len(tuning),
        optimizer_state={"schema": "adam-default-betas-eps/v1", "parameters": {}},
        progress={"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        parent_checkpoint_sha256=parent_sha256)
    learning.validate_checkpoint(branch)
    return branch


def _train_options(epochs, max_seconds, max_optimizer_steps):
    _require(type(epochs) is int and 1 <= epochs <= 1000, "bounded positive epochs required")
    _require(type(max_optimizer_steps) is int and 1 <= max_optimizer_steps <= 100000,
             "at least one bounded actual optimizer step is required")
    _require(type(max_seconds) in (int, float) and 0 < max_seconds <= 3600,
             "positive bounded training deadline required")


@dataclass(frozen=True, slots=True)
class FormulaClientResult:
    update: object
    _checkpoint_json: bytes
    _report_json: bytes
    _branch_json: bytes

    @property
    def checkpoint(self):
        return json.loads(self._checkpoint_json)

    @property
    def report(self):
        return json.loads(self._report_json)

    @property
    def branch_receipt(self):
        return json.loads(self._branch_json)


def train_formula_client(base, round_spec, client_id, training_rows, tuning_rows, *,
                         local_data_sha256, max_seconds=60, epochs=1, max_optimizer_steps=None):
    """Run a genuine local warm-start branch, with fresh Adam and local corpus.

    Rows must already be independently verified against the unchanged core and
    embedding producer. The approved sample count must equal training row count.
    This profile is CPU-only, matching the pinned formula implementation.
    """
    base = _base(base)
    with _cpu():
        round_spec = _round(base, round_spec)
        client = next((item for item in round_spec.clients if item.client_id == client_id), None)
        _require(client is not None, "client is not approved")
        head = base.head
        training, tuning = _rows(training_rows, tuning_rows, head)
        actual_data = formula_local_data_digest(training, tuning)
        _require(local_data_sha256 == client.local_data_sha256 == actual_data,
                 "approved local corpus digest differs")
        _require(client.sample_count == len(training), "approved training sample count differs")
        steps = round_spec.max_local_steps if max_optimizer_steps is None else max_optimizer_steps
        _train_options(epochs, max_seconds, steps)
        _require(steps <= round_spec.max_local_steps, "local optimizer step limit exceeds the round")
        branch = _local_branch(head, training, tuning, base.head_sha256)
        specs, initial = _parameters(head)
        receipt = {"schema": BRANCH_SCHEMA, "profile": PROFILE,
            "round_sha256": round_spec.round_sha256, "client_id": client.client_id,
            "parent_artifact_sha256": base.base_sha256, "parent_head_sha256": base.head_sha256,
            "initial_parameters_sha256": parameter_digest(specs, initial),
            "local_data_sha256": actual_data, "training_count": len(training),
            "tuning_count": len(tuning), "optimizer_policy": "fresh_local_adam",
            "historical_resume": False, "core_changed": False,
            "initial_progress": branch["progress"], "initial_optimizer_parameters": {}, **_FALSE}
        learning = _learning()
        result = learning.train(branch, training, tuning, epochs=epochs,
                                max_seconds=max_seconds, max_optimizer_steps=steps)
        actual_steps = result["report"]["optimizer_steps"]
        _require(actual_steps > 0, "local training completed no optimizer step")
        learning.validate_checkpoint(result["checkpoint"], expected_binding=head["binding"])
        _, final = _parameters(result["checkpoint"])
        deltas = {name: [value - old for value, old in zip(values, initial[name])]
                  for name, values in final.items()}
        update = make_client_update(round_spec, client.client_id, deltas,
            local_steps=actual_steps, local_data_sha256=actual_data)
        _round(base, round_spec)  # Source/core identity must still match after training.
        receipt.update(local_optimizer_steps=actual_steps,
                       local_checkpoint_sha256=learning.checkpoint_digest(result["checkpoint"]))
        return FormulaClientResult(update, _raw(result["checkpoint"]),
                                   _raw(result["report"]), _raw(receipt))


def _round_from_manifest(manifest):
    round_spec = FederatedRound(**{name: manifest[name] for name in (
        "round_id", "model_id", "lineage_id", "dimension", "architecture", "runtime_profile",
        "base_sha256", "base_parameters_sha256", "embedding_producer_sha256", "max_local_steps")},
        parameters=[ParameterSpec(**item) for item in manifest["parameters"]],
        clients=[ClientSpec(**item) for item in manifest["clients"]])
    _require(manifest == round_spec.manifest, "closed canonical federated round required")
    return round_spec


@dataclass(frozen=True, slots=True)
class FederatedFormulaCandidate:
    """Provisional aggregate; it has no historical optimizer/corpus cursor."""

    _base: VerifiedFormulaBase
    _payload_json: bytes

    def __post_init__(self):
        base = _base(self._base)
        value = _parse(self._payload_json)
        with _cpu():
            _validate_candidate(base, value)
        object.__setattr__(self, "_base", base)

    @property
    def payload(self):
        return _parse(self._payload_json)

    @property
    def model_state(self):
        return self.payload["model_state"]

    @property
    def candidate_sha256(self):
        return hashlib.sha256(self._payload_json).hexdigest()


def _validate_candidate(base, value):
    fields = {"schema", "profile", "parent_artifact_sha256", "parent_head_sha256", "binding",
              "config", "codec", "implementation", "projection_id", "model_state", "aggregation",
              "aggregate_candidate_sha256", "sources", "optimizer_state", "progress",
              "training_manifest_sha256", "tuning_manifest_sha256", *_FALSE}
    _require(set(value) == fields and value["schema"] == CANDIDATE_SCHEMA and value["profile"] == PROFILE
             and all(value[key] is False for key in _FALSE), "closed unqualified formula aggregate required")
    _require(all(value[key] is None for key in ("optimizer_state", "progress", "training_manifest_sha256",
                                               "tuning_manifest_sha256")),
             "aggregate cannot invent historical optimizer or corpus progress")
    head = base.head
    _require(value["parent_artifact_sha256"] == base.base_sha256
             and value["parent_head_sha256"] == base.head_sha256
             and value["sources"] == _source_profile(), "aggregate parent or source differs")
    for name in ("binding", "config", "codec", "implementation", "projection_id"):
        _require(value[name] == head[name], "aggregate fixed " + name + " differs")
    specs, parameters = _parameters({**head, "model_state": value["model_state"]})
    provenance = value["aggregation"]
    round_spec = _round(base, _round_from_manifest(provenance["round"]))
    rows = tuple((spec.name, tuple(parameters[spec.name])) for spec in specs)
    AggregateCandidate(rows, _raw(provenance), value["aggregate_candidate_sha256"])
    _require(round_spec.round_sha256 == provenance["round_sha256"], "aggregate round differs")


def aggregate_formula_round(base, round_spec, updates):
    """Average same-base client deltas, retaining fixed head/core context."""
    base = _base(base)
    with _cpu():
        round_spec = _round(base, round_spec)
        head = base.head
        specs, parameters = _parameters(head)
        aggregate = aggregate_round(round_spec, parameters, updates)
        value = {"schema": CANDIDATE_SCHEMA, "profile": PROFILE,
            "parent_artifact_sha256": base.base_sha256, "parent_head_sha256": base.head_sha256,
            **{name: head[name] for name in ("binding", "config", "codec", "implementation", "projection_id")},
            "model_state": _model_state(specs, aggregate.parameters),
            "aggregation": aggregate.provenance, "aggregate_candidate_sha256": aggregate.candidate_sha256,
            "sources": _source_profile(), "optimizer_state": None, "progress": None,
            "training_manifest_sha256": None, "tuning_manifest_sha256": None, **_FALSE}
        return FederatedFormulaCandidate(base, _raw(value))


def save_formula_candidate(candidate, path):
    _require(type(candidate) is FederatedFormulaCandidate, "FederatedFormulaCandidate required")
    checked = FederatedFormulaCandidate(candidate._base, candidate._payload_json)
    with Path(path).open("xb") as stream:
        stream.write(checked._payload_json)
    return {"path": str(Path(path).absolute()), "sha256": checked.candidate_sha256,
            "bytes": len(checked._payload_json), **_FALSE}


def load_formula_candidate(path, *, expected_sha256, base):
    return FederatedFormulaCandidate(base, _read(path, expected_sha256))


def finalize_with_owner_training(candidate, training_rows, tuning_rows, *, owner_data_sha256,
                                 max_optimizer_steps=1, max_seconds=60, epochs=1):
    """Train a fresh owner branch for real before returning a valid v1 head.

    Final weights include the owner's actual updates after averaging; they are
    therefore a separate child of the provisional aggregate. Its v1 manifests,
    Adam moments and progress describe only this new owner corpus/training run.
    The caller verifies rows against the unchanged core and embedding producer.
    """
    _require(type(candidate) is FederatedFormulaCandidate, "FederatedFormulaCandidate required")
    candidate = FederatedFormulaCandidate(candidate._base, candidate._payload_json)
    with _cpu():
        _train_options(epochs, max_seconds, max_optimizer_steps)
        payload = candidate.payload
        template = candidate._base.head
        template["model_state"] = payload["model_state"]
        training, tuning = _rows(training_rows, tuning_rows, template)
        actual_data = formula_local_data_digest(training, tuning)
        _require(owner_data_sha256 == actual_data, "owner corpus digest differs")
        branch = _local_branch(template, training, tuning, candidate.candidate_sha256)
        learning = _learning()
        specs, initial = _parameters(branch)
        _require(parameter_digest(specs, initial) == payload["aggregation"]["parameters_sha256"],
                 "owner branch does not start from the aggregate parameters")
        result = learning.train(branch, training, tuning, epochs=epochs,
                                max_seconds=max_seconds, max_optimizer_steps=max_optimizer_steps)
        actual_steps = result["report"]["optimizer_steps"]
        _require(actual_steps > 0, "owner training completed no actual optimizer step")
        learning.validate_checkpoint(result["checkpoint"], expected_binding=payload["binding"])
        _validate_candidate(candidate._base, payload)
        _, final = _parameters(result["checkpoint"])
        receipt = {"schema": FINALIZATION_SCHEMA, "profile": PROFILE,
            "aggregate_artifact_sha256": candidate.candidate_sha256,
            "aggregate_candidate_sha256": payload["aggregate_candidate_sha256"],
            "initial_parameters_sha256": parameter_digest(specs, initial),
            "final_parameters_sha256": parameter_digest(specs, final),
            "owner_data_sha256": actual_data, "training_count": len(training), "tuning_count": len(tuning),
            "owner_optimizer_steps": actual_steps, "progress": result["checkpoint"]["progress"],
            "optimizer_policy": "fresh_owner_adam", "historical_resume": False,
            "core_changed": False, "checkpoint_sha256": learning.checkpoint_digest(result["checkpoint"]),
            **_FALSE}
        return {"checkpoint": result["checkpoint"], "report": result["report"], "receipt": receipt}


__all__ = ["PROFILE", "CANDIDATE_SCHEMA", "VerifiedFormulaBase", "FormulaClientResult",
           "FederatedFormulaCandidate", "load_formula_base", "load_legal384_formula_base",
           "formula_embedding_digest", "prepare_legal384_formula_rows", "formula_local_data_digest", "create_formula_round",
           "train_formula_client", "aggregate_formula_round", "save_formula_candidate",
           "load_formula_candidate", "finalize_with_owner_training"]

"""Bounded source-bound CodebaseIR feature candidates and exact continuation.

The structural source owner and numerical model registry keep their independent
authorities. A private candidate contains features, weights and Adam state;
it is never a formula, runtime theorem, promoted head or planner fact.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import hashlib
import importlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import sysconfig
import tempfile
import threading
import time
import uuid
from typing import Any

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.backends.codebase_process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_runtime_8d as runtimes
from .codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured

SCHEMA = "codebase-source-feature-training@1"
PROVENANCE_SCHEMA = "codebase-source-feature-lineage@1"
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "promotion_performed": False, "proof_authority": False,
          "source_runtime_semantics_verified": False, "behavioral_satisfaction": False,
          "admission_authority": False, "completion_authority": False}
_PROVENANCE_FIELDS = {"schema", "head", "selections", "parent_version_id", "continuation",
    "training_targets", "tuning_targets", "canary_targets", "replay_targets",
    "ancestral_training", "current_evaluation_bindings", "implementation",
    "contract_sha256", "feature_space_sha256", "canary_monitoring", "replay_monitoring", *_FALSE}


class CodebaseFeatureTrainingError(ValueError):
    """A source, split, state, native execution or lineage binding is invalid."""


def _require(condition, message):
    if not condition:
        raise CodebaseFeatureTrainingError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodebaseFeatureTrainingError("bounded inert native JSON required") from exc


def _text(value, name, maximum=256):
    _require(type(value) is str and value and value == value.strip()
             and len(value.encode("utf-8")) <= maximum and not any(ord(char) < 32 for char in value),
             "invalid bounded " + name)
    return value


@dataclass(frozen=True, slots=True)
class CodebaseTrainingSelection:
    path: str
    role: str
    contracts: tuple = ()

    def __post_init__(self):
        from ipfs_datasets_py.logic.software_verification.codebase_pipeline import ContractSpec
        _text(self.path, "path", 1024)
        path = PurePosixPath(self.path)
        _require(not path.is_absolute() and path.as_posix() == self.path
                 and ".." not in path.parts and self.path.endswith(".py"), "canonical Python path required")
        _require(self.role in {"train", "tune", "canary"}, "explicit train/tune/canary role required")
        _require(type(self.contracts) in {tuple, list} and len(self.contracts) <= 8
                 and all(type(item) is ContractSpec for item in self.contracts), "native bounded contracts required")
        copied = tuple(ContractSpec(item.function_name, tuple(item.preconditions), tuple(item.postconditions),
                                    item.contract_id) for item in self.contracts)
        _require([item.to_dict() for item in copied] == [item.to_dict() for item in self.contracts],
                 "mutated contract selection")
        object.__setattr__(self, "contracts", copied)

    def to_dict(self):
        return {"path": self.path, "role": self.role, "contracts": [item.to_dict() for item in self.contracts]}

    @classmethod
    def from_dict(cls, value):
        from ipfs_datasets_py.logic.software_verification.codebase_pipeline import ContractSpec
        _require(type(value) is dict and set(value) == {"path", "role", "contracts"}, "closed selection required")
        result = cls(value["path"], value["role"], tuple(ContractSpec(**row) for row in value["contracts"]))
        _require(result.to_dict() == value, "noncanonical selection")
        return result


@dataclass(frozen=True, slots=True)
class CodebaseFeatureTrainingLimits:
    max_selections: int = 16
    max_targets: int = 32
    max_features: int = 1024
    max_ancestry: int = 8
    max_training_history: int = 128
    max_target_bytes: int = 8 * 1024 * 1024
    max_candidate_bytes: int = 16 * 1024 * 1024
    max_ancestry_bytes: int = 32 * 1024 * 1024

    def __post_init__(self):
        for field in self.__dataclass_fields__:
            _require(type(getattr(self, field)) is int and getattr(self, field) > 0, "positive native limits required")
        _require(self.max_features <= features.MAX_FEATURES and self.max_targets <= 1024
                 and self.max_candidate_bytes <= runtimes.MAX_CANDIDATE_BYTES, "limits exceed native backend")


@dataclass(frozen=True, slots=True)
class CodebaseFeatureTrainingRecord:
    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self):
        _require(type(self._payload) is bytes and type(self.observed_live) is bool, "immutable record required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid
                 and value["schema"] == SCHEMA and type(value["authority"]) is dict
                 and set(value["authority"]) == set(_FALSE)
                 and all(flag is False for flag in value["authority"].values()), "record identity/authority differs")

    def to_dict(self):
        return json.loads(self._payload)


def _targets_adapter():
    return importlib.import_module("ipfs_datasets_py.logic.software_contracts.codebase_ir_targets")


def _pins():
    names = (__name__, "ipfs_datasets_py.logic.software_contracts.codebase_ir_targets",
             runtimes.__name__, features.__name__,
             "ipfs_datasets_py.optimizers.logic_theorem_optimizer.codebase_feature_worker",
             "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_cuda")
    values = {}
    for name in names:
        module = importlib.import_module(name)
        values[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {"files": values, "sha256": features.digest(values),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _native_owners(index, registry):
    _require(type(index) is RepositoryCodebaseIndex and index.catalog is not None
             and type(registry) is AutoencoderRegistry, "exact native source and model owners required")
    databases = index.catalog.store._connection.execute("PRAGMA database_list").fetchall()
    _require(not any(row[2] and Path(row[2]).resolve() == registry.database_path for row in databases),
             "separate native owner database files required")
    registry._ensure_owner()


def _selections(values, limits):
    _require(type(values) in {tuple, list} and 3 <= len(values) <= limits.max_selections
             and all(type(item) is CodebaseTrainingSelection for item in values), "bounded explicit source splits required")
    result = tuple(sorted((CodebaseTrainingSelection.from_dict(item.to_dict()) for item in values), key=lambda x: x.path))
    _require(len({item.path for item in result}) == len(result) and {item.role for item in result} == {"train", "tune", "canary"},
             "unique paths and all three split roles required")
    return result


def _binding(target):
    return _targets_adapter().source_binding_from_target(target)


def _identity(target):
    binding = _binding(target)
    head = binding["head"]
    return {"repository_id": head["repository_id"], "path": binding["path"],
            "source_digest": binding["content_sha256"]}


def _split_check(train, tune, canary, history):
    identities = [[_identity(target) for target in batch] for batch in (train, tune, canary)]
    def paths(rows):
        return {(row["repository_id"], row["path"]) for row in rows}
    def digests(rows):
        return {row["source_digest"] for row in rows}
    left = [*history, *identities[0]]
    _require(not paths(left) & paths(identities[1] + identities[2])
             and not digests(left) & digests(identities[1] + identities[2])
             and not paths(identities[1]) & paths(identities[2])
             and not digests(identities[1]) & digests(identities[2]),
             "ancestral content/path train/tune/canary leakage")


def _batch(values, limits):
    from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    _require(type(values) in {list, tuple} and 1 <= len(values) <= limits.max_targets, "bounded target batch required")
    _require(len(_wire([item.to_dict() if hasattr(item, "to_dict") else item for item in values])) <= limits.max_target_bytes,
             "target batch byte bound exceeded")
    adapter = _targets_adapter()
    return [adapter.validate_codebase_targets(DomainTargetEnvelope.from_dict(value) if type(value) is dict else value)
            for value in values]


def _read_candidate(registry, version_id, limits):
    row = registry.get_version(version_id)
    _require(row["artifact"]["bytes"] <= limits.max_candidate_bytes, "candidate byte bound exceeded")
    saved = runtimes._read_candidate(registry, row)
    _require(len(_wire(saved)) <= limits.max_candidate_bytes, "candidate payload exceeds byte bound")
    with registry.artifact_path(row["artifact"]).open("rb") as stream:
        raw = stream.read(limits.max_candidate_bytes + 1)
    _require(raw == _wire(saved) and hashlib.sha256(raw).hexdigest() == row["artifact"]["sha256"],
             "source-bound checkpoint must retain exact canonical native bytes")
    return row, saved


def _request(provenance, configuration):
    return {"schema": SCHEMA, "head": provenance["head"], "selections": provenance["selections"],
        "parent_version_id": provenance["parent_version_id"], "contract_sha256": provenance["contract_sha256"],
        "training_targets_sha256": features.digest(provenance["training_targets"]),
        "tuning_targets_sha256": features.digest(provenance["tuning_targets"]),
        "canary_targets_sha256": features.digest(provenance["canary_targets"]),
        "configuration": {key: configuration[key] for key in ("epochs", "learning_rate", "seed")},
        "implementation": provenance["implementation"]}


def _diagnostic(value, targets, state, contract_sha, space):
    expected = {"source_digests", "mean_squared_errors", "mean_squared_error", "coverage",
                "inference", "used_for_selection", "semantic_or_property_evaluation"}
    _require(type(value) is dict and set(value) == expected and value["used_for_selection"] is False
             and value["semantic_or_property_evaluation"] is False, "closed nonselecting feature diagnostic required")
    vectors, identities, coverage = features._matrix(space, targets)
    inference = value["inference"]
    inference_fields = {"schema", "contract_sha256", "state_sha256", "feature_space_sha256", "rows", "coverage",
                        "training_executed", "decoded_formulas_generated", "representation", *features.FALSE}
    _require(type(inference) is dict and set(inference) == inference_fields
        and inference.get("schema") == "native-projection-feature-inference/v1"
        and inference.get("contract_sha256") == contract_sha
        and inference.get("state_sha256") == features.digest(state)
        and inference.get("feature_space_sha256") == features.digest(space)
        and inference.get("training_executed") is False and inference.get("decoded_formulas_generated") is False
        and all(inference.get(key) is False for key in features.FALSE)
        and inference.get("coverage") == coverage and value["coverage"] == coverage
        and value["source_digests"] == identities, "diagnostic state/target/authority binding differs")
    rows = inference.get("rows")
    _require(type(rows) is list and len(rows) == len(vectors)
        and [row.get("source_digest") for row in rows] == identities, "diagnostic source inventory differs")
    losses = []
    for vector, row in zip(vectors, rows):
        _require(type(row) is dict and set(row) == {"source_digest", "latent", "reconstructed_projection_features"}
            and type(row["latent"]) is list and len(row["latent"]) == state["latent_width"]
            and set(row["reconstructed_projection_features"]) == set(space["projection_ids"])
            and all(type(row["reconstructed_projection_features"][name]) is list
                and len(row["reconstructed_projection_features"][name]) == sum(column[0] == name for column in space["columns"])
                for name in space["projection_ids"]), "diagnostic feature layout differs")
        decoded = [item for name in space["projection_ids"] for item in row["reconstructed_projection_features"][name]]
        _require(len(decoded) == len(vector) and all(type(item) in {int, float} and math.isfinite(item)
                     for item in [*row["latent"], *decoded]), "invalid diagnostic numerical values")
        losses.append(sum((left - right) ** 2 for left, right in zip(vector, decoded)) / len(vector))
    _require(value["mean_squared_errors"] == losses and value["mean_squared_error"] == sum(losses) / len(losses),
             "recorded diagnostic losses differ from recorded feature rows")
    # Replay the exact numerical decoder, not just self-consistent saved
    # metrics. These small structural feature vectors come from the native
    # captured-source adapter; this is inference, never fitting or a proof.
    replay_contract = features.build_native_feature_contract(space,
        ir_schema=runtimes.CODEBASE_SOURCE_FEATURE_SCHEMA,
        adapter_sha256=hashlib.sha256(Path(_targets_adapter().__file__).read_bytes()).hexdigest(),
        latent_width=state["latent_width"])
    _require(replay_contract.sha256 == contract_sha, "diagnostic native contract differs")
    replayed = features.infer_projection_features(replay_contract, space, state, targets)
    _require(replayed == inference, "independently replayed numerical feature diagnostic differs")


def _lineage(index, registry, version_id, limits):
    """Replay bounded ancestry and its native target/source/split bindings."""
    chain, seen, total = [], set(), 0
    current = version_id
    while current is not None:
        _require(current not in seen and len(chain) < limits.max_ancestry, "cyclic or oversized model ancestry")
        seen.add(current)
        row, saved = _read_candidate(registry, current, limits)
        total += row["artifact"]["bytes"]
        _require(total <= limits.max_ancestry_bytes, "ancestry bytes exceed bound")
        runtimes.load_version(registry, current, domain="codebase_ir", version=runtimes.CODEBASE_SOURCE_FEATURE_VERSION)
        provenance = saved["report"].get("codebase_provenance")
        _require(type(provenance) is dict and set(provenance) == _PROVENANCE_FIELDS
                 and provenance["schema"] == PROVENANCE_SCHEMA
                 and all(provenance[key] is False for key in _FALSE), "closed nonauthoritative CodebaseIR lineage required")
        _require(provenance["parent_version_id"] == row["parent_version_id"]
                 and provenance["contract_sha256"] == saved["state"]["contract_sha256"]
                 and provenance["feature_space_sha256"] == features.digest(saved["feature_space"])
                 and provenance["implementation"] == _pins(), "lineage model/producer binding differs")
        selections = _selections([CodebaseTrainingSelection.from_dict(item) for item in provenance["selections"]], limits)
        head = CodebaseHead.from_dict(provenance["head"])
        train = _batch(provenance["training_targets"], limits)
        tune = _batch(provenance["tuning_targets"], limits)
        canary = _batch(provenance["canary_targets"], limits)
        replay = _batch(provenance["replay_targets"], limits)
        history = provenance["ancestral_training"]
        _require(type(history) is list and len(history) <= limits.max_training_history
                 and all(type(item) is dict and set(item) == {"repository_id", "path", "source_digest"} for item in history),
                 "bounded closed training history required")
        _split_check(train, tune, canary, history)
        _require(saved["report"]["training_targets_sha256"] == features.digest([item.to_dict() for item in train])
                 and saved["report"]["tuning_targets_sha256"] == features.digest([item.to_dict() for item in tune])
                 and saved["state"]["tuning_targets_sha256"] == saved["report"]["tuning_targets_sha256"]
                 and saved["state"]["optimizer_config"]["learning_rate"] == saved["report"]["configuration"]["learning_rate"],
                 "training/tuning target inventories differ from native report")
        request = _request(provenance, saved["report"]["configuration"])
        _require(saved["report"].get("codebase_request_sha256") == features.digest(request), "training request digest differs")
        if row["parent_version_id"] is not None:
            completion = registry.get_run_completion(row["metadata"]["producer_run"])
            _require(completion is not None and completion["candidate_version"] == row
                     and completion["run"]["spec"] == request, "native completed run belongs to another source/cohort request")
        monitor = provenance["canary_monitoring"]
        _require(type(monitor) is dict and set(monitor) == {"before", "after", "purpose", "used_for_selection"}
            and monitor["purpose"] == "repeated_post_selection_diagnostic_not_unseen_qualification"
            and monitor["used_for_selection"] is False, "canary selection/qualification policy differs")
        _diagnostic(monitor["after"], canary, saved["state"], saved["state"]["contract_sha256"], saved["feature_space"])
        _diagnostic(provenance["replay_monitoring"], replay, saved["state"], saved["state"]["contract_sha256"], saved["feature_space"])
        receipt = saved["report"].get("codebase_worker_receipt")
        _require(type(receipt) is dict and set(receipt) == {"executable_sha256", "worker_sha256", "input_sha256",
            "output_sha256", "elapsed_ms", "returncode", "workspace_cleaned", "limits", "memory_enforcement",
            "source_execution_attested"} and receipt["returncode"] == 0 and receipt["workspace_cleaned"] is True
            and receipt["source_execution_attested"] is False and type(receipt["elapsed_ms"]) is int
            and receipt["elapsed_ms"] >= 0 and receipt["memory_enforcement"] == "sampled_process_tree_rss_with_possible_overshoot"
            and all(type(receipt[key]) is str and re.fullmatch(r"[0-9a-f]{64}", receipt[key])
                    for key in ("executable_sha256", "worker_sha256", "input_sha256", "output_sha256")),
            "native worker receipt binding/authority differs")
        current_train = []
        evaluation_bindings = []
        current_evaluation = {"tune": [], "canary": []}
        for selection in selections:
            target = _targets_adapter().prepare_codebase_targets(index, expected_head=head, path=selection.path,
                                                                 contracts=selection.contracts)
            if selection.role == "train":
                current_train.append(target)
            else:
                evaluation_bindings.append({"role": selection.role, "binding": _binding(target)})
                current_evaluation[selection.role].append(target)
        _require(provenance["current_evaluation_bindings"] == evaluation_bindings, "current evaluation source refs differ")
        for role, fixed in (("tune", tune), ("canary", canary)):
            _require([_identity(target) for target in current_evaluation[role]] == [_identity(target) for target in fixed]
                     and [target.to_dict()["projections"] for target in current_evaluation[role]] == [target.to_dict()["projections"] for target in fixed],
                     "fixed evaluation source/features differ from captured observations")
        present = {_binding(target)["content_sha256"] for target in current_train}
        expected_train = [*current_train, *(target for target in replay if _binding(target)["content_sha256"] not in present)]
        _require([item.to_dict() for item in train] == [item.to_dict() for item in expected_train],
                 "current source/replay training membership differs")
        chain.append((row, saved, provenance, train, tune, canary, replay))
        current = row["parent_version_id"]
    for child, parent in zip(chain, chain[1:]):
        _, saved, provenance, train, tune, canary, replay = child
        _, parent_saved, parent_provenance, parent_train, parent_tune, parent_canary, parent_replay = parent
        expected_history = sorted({features.digest(item): item for item in
            [*parent_provenance["ancestral_training"], *(_identity(item) for item in parent_train)]}.values(),
            key=lambda item: (item["repository_id"], item["path"], item["source_digest"]))
        _require(provenance["ancestral_training"] == expected_history
                 and [x.to_dict() for x in tune] == [x.to_dict() for x in parent_tune]
                 and [x.to_dict() for x in canary] == [x.to_dict() for x in parent_canary]
                 and [x.to_dict() for x in replay] == [x.to_dict() for x in parent_replay]
                 and provenance["selections"] == parent_provenance["selections"]
                 and saved["contract"] == parent_saved["contract"]
                 and saved["feature_space"] == parent_saved["feature_space"]
                 and saved["report"]["base_state_sha256"] == features.digest(parent_saved["state"])
                 and provenance["continuation"] == "exact_frozen_basis_adam_resume", "ancestral continuation differs")
        _diagnostic(provenance["canary_monitoring"]["before"], canary, parent_saved["state"],
                    parent_saved["state"]["contract_sha256"], saved["feature_space"])
    root = chain[-1]
    _require(root[2]["ancestral_training"] == [] and root[2]["continuation"] == "fresh_feature_basis",
             "root lineage cannot claim inherited training")
    _require([target.to_dict() for target in root[3]] == [target.to_dict() for target in root[6]]
        and all(_binding(target)["head"] == root[2]["head"] for target in [*root[4], *root[5]]),
        "root replay/evaluation cohort differs from its captured source head")
    _require(root[2]["canary_monitoring"]["before"] is None, "fresh root cannot claim inherited canary execution")
    return chain


@contextmanager
def _resources(index, repository, head, *, scheduler, parent_lease, cancel_event,
               admission_timeout_seconds, timeout_seconds, memory_mb, limits):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
    _require(type(head) is CodebaseHead and type(timeout_seconds) in {int, float}
             and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600, "exact source head and bounded deadline required")
    _require(type(memory_mb) is int and memory_mb >= 512, "at least 512 MB reserved for native numerical worker")
    _require(limits.max_ancestry_bytes + 2 * limits.max_candidate_bytes + limits.max_target_bytes <= memory_mb * 1024 * 1024 // 4,
             "retained byte bounds exceed admission envelope")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def checkpoint():
            if signal.is_set():
                raise LeaseCancelledError("CodebaseIR training cancelled")
            if time.monotonic() >= deadline:
                raise LeaseTimeoutError("CodebaseIR training deadline exceeded")
            return deadline - time.monotonic()
        def observe():
            remaining = checkpoint()
            index.observe_current(repository, expected_head=head, parent_lease=lease, cancel_event=signal,
                timeout_seconds=remaining, admission_timeout_seconds=min(admission_timeout_seconds, remaining), memory_mb=memory_mb)
            checkpoint()
        observe()
        yield lease, signal, checkpoint, observe
        observe()


def _worker(runtime, train, tune, canary, replay, *, action, epochs, learning_rate, seed,
            remaining, memory_mb, limits, signal, lease):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_feature_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    payload = {"schema": worker.SCHEMA, "action": action, "contract": runtime.contract.to_dict(),
        "feature_space": runtime.feature_space, "base_state": runtime.state,
        "training_targets": [item.to_dict() for item in train], "tuning_targets": [item.to_dict() for item in tune],
        "canary_targets": [item.to_dict() for item in canary], "replay_targets": [item.to_dict() for item in replay],
        "epochs": epochs, "learning_rate": learning_rate, "seed": seed,
        "max_seconds": min(300.0, remaining())}
    raw = _wire(payload)
    _require(len(raw) <= limits.max_candidate_bytes, "native worker request exceeds byte bound")
    executable, script = Path(sys.executable).resolve(), Path(worker.__file__).resolve()
    torch_spec = importlib.util.find_spec("torch")
    _require(torch_spec is not None and torch_spec.origin is not None,
             "installed Torch dependency required")
    libraries = list(dict.fromkeys((str(Path(sysconfig.get_path("purelib")).resolve()),
                                   str(Path(torch_spec.origin).resolve().parent.parent))))
    _require(all(Path(path).is_dir() for path in libraries), "installed numerical library paths unavailable")
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    bounds = ToolRunLimits(timeout_seconds=remaining(), resident_memory_bytes=memory_mb * 1024 * 1024,
        max_output_bytes=limits.max_candidate_bytes, max_input_bytes=limits.max_candidate_bytes,
        max_workspace_bytes=2 * limits.max_candidate_bytes)
    with lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=memory_mb,
            child_process_slots=1, timeout=remaining(), cancel_event=signal,
            request_id="codebase-source-feature:" + action) as numerical_lease:
        process = run_bounded_stdin_tool([str(executable), "-I", "-B", str(script), json.dumps(libraries)],
                                        raw, runner=runner, limits=bounds,
                                        cancellation=numerical_lease.combined_cancellation_signal(signal))
    remaining()
    _require(process.returncode == 0 and not any((process.timed_out, process.cancelled, process.unavailable,
        process.output_truncated, process.resource_exhausted)) and process.workspace_cleaned,
        "native feature worker failed: " + str(process.termination_reason or process.error or "execution error")
        + ": " + process.stderr[-2048:])
    decoded = json.loads(process.stdout)
    _require(len(_wire(decoded)) <= limits.max_candidate_bytes and decoded["schema"] == worker.SCHEMA,
             "native feature worker output binding differs")
    receipt = {"executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "worker_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "input_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(process.stdout.encode("utf-8")).hexdigest(),
        "elapsed_ms": process.elapsed_ms, "returncode": process.returncode,
        "workspace_cleaned": process.workspace_cleaned, "limits": {
            "resident_memory_bytes": bounds.resident_memory_bytes, "max_output_bytes": bounds.max_output_bytes},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot",
        "source_execution_attested": False}
    return decoded, receipt


def _bootstrap_replay(index, registry, operation_id, request_id, limits):
    """Read a native operation then let its owner validate the complete payload."""
    native_operation = "codebase-bootstrap:" + operation_id
    with registry._transaction() as connection:
        rows = connection.execute("SELECT receipt FROM autoencoder_control.operations WHERE operation_id=? LIMIT 2",
                                  [native_operation]).fetchall()
    if not rows:
        return None
    _require(len(rows) == 1 and len(rows[0][0].encode("utf-8")) <= 64 * 1024, "bounded native bootstrap operation required")
    receipt = json.loads(rows[0][0])
    row, saved = _read_candidate(registry, receipt["version_id"], limits)
    payload = {"variant_id": row["variant_id"], "artifact": row["artifact"], "metadata": row["metadata"],
               "parent_version_id": None}
    _require(row["parent_version_id"] is None
        and registry.resolve_operation(native_operation, "RegisterVersion", payload) == receipt
        and saved["report"]["codebase_request_sha256"] == request_id,
        "bootstrap operation belongs to another exact training request")
    return _derive_training_record(index, registry, row["version_id"], limits=limits)


_BOOTSTRAP_GUARD = threading.Lock()
_ACTIVE_BOOTSTRAPS = set()


def _serialize_bootstrap(function):
    @wraps(function)
    def guarded(index, repository, *, registry, parent_version_id=None, **kwargs):
        if parent_version_id is not None:
            return function(index, repository, registry=registry, parent_version_id=parent_version_id, **kwargs)
        _require(type(registry) is AutoencoderRegistry, "native model registry owner required")
        # Native exclusive registry ownership fences other processes. This
        # transient guard refuses a duplicate local root fitting operation
        # without holding native SQL locks or delaying child lease updates.
        operation_id = _text(kwargs.get("operation_id"), "operation_id", 128)
        key = (registry, operation_id)
        with _BOOTSTRAP_GUARD:
            _require(key not in _ACTIVE_BOOTSTRAPS,
                     "bootstrap operation already active; retry after completion")
            _ACTIVE_BOOTSTRAPS.add(key)
        try:
            return function(index, repository, registry=registry, parent_version_id=None, **kwargs)
        finally:
            with _BOOTSTRAP_GUARD:
                _ACTIVE_BOOTSTRAPS.remove(key)
    return guarded


@_serialize_bootstrap
def train_current_codebase_features(index, repository, *, expected_head, registry, selections, operation_id,
        parent_version_id=None, epochs=3, learning_rate=0.02, seed=1729, limits=None,
        scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Train/register a private root or source-successor child; never promote.

    Root samples define the feature basis. Children preserve that basis, saved
    optimizer and original tuning/canary/replay envelopes. An immutable native
    run ID permits one ordered completion; repeated completed calls resolve
    history without fitting. Rejected/cancelled work cannot move a model head.
    """
    _native_owners(index, registry)
    _text(operation_id, "operation_id")
    _require(len(operation_id) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    limits = CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is CodebaseFeatureTrainingLimits, "native training limits required")
    selections = _selections(selections, limits)
    _require(type(epochs) is int and 1 <= epochs <= 32 and type(seed) is int and 0 <= seed < 2**31
             and type(learning_rate) in {int, float} and math.isfinite(learning_rate) and 0 < learning_rate <= 0.1,
             "bounded exact numerical configuration required")
    with _resources(index, repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (lease, signal, remaining, observe):
        pins = _pins()
        grouped = {role: [] for role in ("train", "tune", "canary")}
        eval_bindings = []
        for selection in selections:
            remaining()
            target = _targets_adapter().prepare_codebase_targets(index, expected_head=expected_head,
                path=selection.path, contracts=selection.contracts)
            _require(target.ready_for_training, "selected source has unsupported feature extraction")
            grouped[selection.role].append(target)
            if selection.role != "train":
                eval_bindings.append({"role": selection.role, "binding": _binding(target)})
        train, tune, canary, replay, history = grouped["train"], grouped["tune"], grouped["canary"], grouped["train"], []
        lineage = None
        if parent_version_id is None:
            runtime = runtimes.build_source_bound_codebase_runtime(train, latent_width=8)
        else:
            _text(parent_version_id, "parent_version_id", 512)
            lineage = _lineage(index, registry, parent_version_id, limits)
            _require(len(lineage) < limits.max_ancestry, "prospective child exceeds model ancestry bound")
            _, saved, parent_provenance, parent_train, tune, canary, replay = lineage[0]
            _require([item.to_dict() for item in selections] == parent_provenance["selections"],
                     "child must retain ancestral paths/contracts/split roles")
            _require(expected_head.repository_id == parent_provenance["head"]["repository_id"], "foreign source lineage")
            for role, fixed in (("tune", tune), ("canary", canary)):
                _require([_binding(target)["content_sha256"] for target in grouped[role]] == [_binding(target)["content_sha256"] for target in fixed]
                    and [target.to_dict()["projections"] for target in grouped[role]] == [target.to_dict()["projections"] for target in fixed],
                    "fixed evaluation source/features changed; declare a new training lineage")
            history = sorted({features.digest(item): item for item in
                [*parent_provenance["ancestral_training"], *(_identity(item) for item in parent_train)]}.values(),
                key=lambda item: (item["repository_id"], item["path"], item["source_digest"]))
            _require(len(history) <= limits.max_training_history, "training history cap reached")
            # Current source wins duplicate content; immutable root replay still
            # contributes changed historical sources without vocabulary fitting.
            present = {_binding(target)["content_sha256"] for target in train}
            train = [*train, *(target for target in replay if _binding(target)["content_sha256"] not in present)]
            runtime = runtimes.load_version(registry, parent_version_id, domain="codebase_ir",
                                           version=runtimes.CODEBASE_SOURCE_FEATURE_VERSION)
        train, tune, canary, replay = [_batch(batch, limits) for batch in (train, tune, canary, replay)]
        _split_check(train, tune, canary, history)
        _require(len(runtime.feature_space["columns"]) <= limits.max_features, "feature allocation exceeds admitted profile")
        if parent_version_id is not None:
            _require(runtime.state["optimizer_config"]["learning_rate"] == float(learning_rate), "optimizer settings changed on exact resume")
        request = {"schema": SCHEMA, "head": expected_head.to_dict(), "selections": [item.to_dict() for item in selections],
            "parent_version_id": parent_version_id, "contract_sha256": runtime.contract.sha256,
            "training_targets_sha256": features.digest([item.to_dict() for item in train]),
            "tuning_targets_sha256": features.digest([item.to_dict() for item in tune]),
            "canary_targets_sha256": features.digest([item.to_dict() for item in canary]),
            "configuration": {"epochs": epochs, "learning_rate": learning_rate, "seed": seed},
            "implementation": pins}
        request_id = features.digest(request)
        run_id = "codebase-source:" + operation_id
        run_lease = None
        if parent_version_id is None:
            previous = _bootstrap_replay(index, registry, operation_id, request_id, limits)
            if previous is not None:
                _publish_training_record(index, previous)
                observe()
                return CodebaseFeatureTrainingRecord(previous.artifact_cid, previous._payload, True)
        if parent_version_id is not None:
            create_payload = {"run_id": run_id, "variant_id": runtime.contract.variant_id,
                              "base_version_id": parent_version_id, "spec": request}
            registry.create_run("codebase-create:" + operation_id, **create_payload)
            completion = registry.get_run_completion(run_id)
            if completion is not None:
                version_id = completion["candidate_version"]["version_id"]
                record = _derive_training_record(index, registry, version_id, limits=limits)
                _publish_training_record(index, record)
                observe()
                return CodebaseFeatureTrainingRecord(record.artifact_cid, record._payload, True)
            invocation = uuid.uuid4().hex
            run_lease = registry.claim_run("codebase-claim:" + operation_id + ":" + invocation,
                run_id, "codebase-source-worker:" + invocation,
                lease_seconds=min(86400.0, remaining() + 5.0))["lease"]
        try:
            worker_result, receipt = _worker(runtime, train, tune, canary, replay, action="train",
                epochs=epochs, learning_rate=learning_rate, seed=seed, remaining=remaining,
                memory_mb=memory_mb, limits=limits, signal=signal, lease=lease)
            result = worker_result["result"]
            features._validate_state(runtime.contract, runtime.feature_space, result["state"])
            _require(result["report"]["contract_sha256"] == runtime.contract.sha256
                and result["report"]["feature_space_sha256"] == features.digest(runtime.feature_space)
                and result["report"]["base_state_sha256"] == (None if runtime.state is None else features.digest(runtime.state))
                and all(result["report"].get(key) is False for key in features.FALSE), "worker state/parent/report binding differs")
            provenance = {"schema": PROVENANCE_SCHEMA, "head": expected_head.to_dict(),
                "selections": [item.to_dict() for item in selections], "parent_version_id": parent_version_id,
                "continuation": "fresh_feature_basis" if parent_version_id is None else "exact_frozen_basis_adam_resume",
                "training_targets": [item.to_dict() for item in train], "tuning_targets": [item.to_dict() for item in tune],
                "canary_targets": [item.to_dict() for item in canary], "replay_targets": [item.to_dict() for item in replay],
                "ancestral_training": history, "current_evaluation_bindings": eval_bindings, "implementation": pins,
                "contract_sha256": runtime.contract.sha256, "feature_space_sha256": features.digest(runtime.feature_space),
                "canary_monitoring": {"before": worker_result["canary_before"], "after": worker_result["canary_after"],
                    "purpose": "repeated_post_selection_diagnostic_not_unseen_qualification", "used_for_selection": False},
                "replay_monitoring": worker_result["replay_after"], **_FALSE}
            result["report"]["codebase_provenance"] = provenance
            result["report"]["codebase_worker_receipt"] = receipt
            result["report"]["codebase_request_sha256"] = request_id
            saved = {"contract": runtime.contract.to_dict(), "feature_space": runtime.feature_space,
                     "state": result["state"], "report": result["report"]}
            raw = _wire(saved)
            _require(len(raw) <= limits.max_candidate_bytes, "candidate exceeds admitted byte bound")
            ancestor_bytes = 0 if lineage is None else sum(item[0]["artifact"]["bytes"] for item in lineage)
            _require(ancestor_bytes + len(raw) <= limits.max_ancestry_bytes,
                     "prospective candidate exceeds model ancestry byte bound")
            _require(_pins() == pins, "numerical producer changed during execution")
            observe()
            if parent_version_id is None:
                with tempfile.TemporaryDirectory(prefix="codebase-stage-", dir=registry.artifact_root) as staging:
                    candidate = features.register_feature_candidate(registry, runtime.contract, runtime.feature_space,
                        result, Path(staging) / "candidate")
                version_id = candidate["version_id"]
                registry.register_version("codebase-bootstrap:" + operation_id, runtime.contract.variant_id,
                    candidate["artifact"], {"contract_sha256": runtime.contract.sha256,
                    "training_purpose": "feature_pretraining", **features.FALSE})
            else:
                with tempfile.TemporaryDirectory(prefix="codebase-stage-", dir=registry.artifact_root) as staging:
                    candidate_path = Path(staging) / "candidate.json"
                    candidate_path.write_bytes(raw)
                    artifact = registry.stage_artifact(candidate_path, hashlib.sha256(raw).hexdigest())
                observe()
                completion_result = {"training_purpose": "feature_pretraining", "contract_sha256": runtime.contract.sha256,
                    "feature_space_sha256": features.digest(runtime.feature_space), "state_sha256": features.digest(result["state"]),
                    "report_sha256": features.digest(result["report"]), **features.FALSE}
                completed = registry.complete_run("codebase-complete:" + operation_id, run_lease, artifact, completion_result)
                run_lease = None
                version_id = completed["version_id"]
            observe()
            record = _derive_training_record(index, registry, version_id, limits=limits)
            _publish_training_record(index, record)
            remaining()
            return CodebaseFeatureTrainingRecord(record.artifact_cid, record._payload, True)
        except BaseException as error:
            if run_lease is not None:
                try:
                    registry.fail_run("codebase-fail:" + operation_id + ":" + str(run_lease["attempt"]), run_lease, {"admitted": False, "qualified": False,
                        "reason": "source_bound_training_incomplete", "promotion_performed": False})
                except Exception as cleanup_error:
                    error.add_note("Native run failure recording also failed: " + str(cleanup_error))
            raise


def _derive_training_record(index, registry, version_id, *, limits=None):
    _native_owners(index, registry)
    limits = CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is CodebaseFeatureTrainingLimits, "native limits required")
    chain = _lineage(index, registry, version_id, limits)
    row, saved, provenance, *_ = chain[0]
    raw = _wire(saved)
    value = {"schema": SCHEMA, "version_id": version_id, "variant_id": row["variant_id"],
        "parent_version_id": row["parent_version_id"], "head": provenance["head"],
        "registry_artifact": row["artifact"], "checkpoint_raw_cid": cid_for_bytes(raw),
        "contract_sha256": saved["state"]["contract_sha256"], "state_sha256": features.digest(saved["state"]),
        "feature_space_sha256": features.digest(saved["feature_space"]),
        "report_json": _wire(saved["report"]).decode("utf-8"), "authority": dict(_FALSE),
        "source_model_generation": "historical_recorded_source_and_private_model_candidate",
        "training_performed_during_load": False, "model_head_selected": False}
    encoded = canonical_dag_json_bytes(value)
    cid = cid_for_structured(value)
    return CodebaseFeatureTrainingRecord(cid, encoded, False)


def _publish_training_record(index, record):
    _require(index.artifacts.put(record.to_dict()) == record.artifact_cid,
             "CAS returned another training record identity")


def load_codebase_feature_training(index, registry, version_id, *, limits=None):
    """Historical source/model replay; no fitting, writes or freshness claim."""
    record = _derive_training_record(index, registry, version_id, limits=limits)
    _require(index.artifacts.get(record.artifact_cid) == record.to_dict(), "published training record is missing or changed")
    return record


def infer_current_codebase_features(index, repository, *, expected_head, registry, version_id, paths,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Explicit current feature inference; no fitting, decoder or model selection."""
    _native_owners(index, registry)
    limits = CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is CodebaseFeatureTrainingLimits and type(paths) in {list, tuple}
        and 1 <= len(paths) <= limits.max_selections and len(set(paths)) == len(paths), "bounded distinct inference paths required")
    with _resources(index, repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (lease, signal, remaining, observe):
        chain = _lineage(index, registry, version_id, limits)
        _require(chain[0][2]["head"] == expected_head.to_dict(), "model belongs to another complete source head")
        runtime = runtimes.load_version(registry, version_id, domain="codebase_ir", version=runtimes.CODEBASE_SOURCE_FEATURE_VERSION)
        selections = {item["path"]: CodebaseTrainingSelection.from_dict(item) for item in chain[0][2]["selections"]}
        targets = []
        for path in paths:
            _require(path in selections, "inference path outside the registered source cohort")
            targets.append(_targets_adapter().prepare_codebase_targets(index, expected_head=expected_head,
                path=path, contracts=selections[path].contracts))
        result, receipt = _worker(runtime, _batch(targets, limits), [], [], [], action="infer", epochs=1,
            learning_rate=0.02, seed=1729, remaining=remaining, memory_mb=memory_mb, limits=limits, signal=signal, lease=lease)
        _require(result["training_executed"] is False and result["proof_authority"] is False,
                 "inference attempted training or authority")
        observe()
        return {"schema": "codebase-current-feature-inference@1", "head": expected_head.to_dict(),
            "version_id": version_id, "inference": result["inference"], "worker_receipt": receipt,
            "training_executed": False, "authority": dict(_FALSE)}


__all__ = ["CodebaseTrainingSelection", "CodebaseFeatureTrainingLimits", "CodebaseFeatureTrainingRecord",
           "CodebaseFeatureTrainingError", "train_current_codebase_features",
           "load_codebase_feature_training", "infer_current_codebase_features"]

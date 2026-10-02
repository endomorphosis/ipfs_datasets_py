"""Source-owned same-parent CodebaseIR feature federation, without promotion.

The initial executor runs bounded private clients sequentially. Binary deltas
use the existing native codec; source and model owners remain independent.
Historical replay checks their complete numeric reduction without fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import uuid

from ipfs_datasets_py.duckdb_control.autoencoder_federated import create_federated_run, complete_federated_run
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_runtime_8d as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    FederatedRound, ParameterSpec, ClientSpec, aggregate_round,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import (
    write_client_update, read_client_update,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import (
    TrainingMode, GradientBackendUnavailable,
)
from . import codebase_source_training as source
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured

SCHEMA = "codebase-source-federated-training@1"
REPORT_SCHEMA = "codebase-source-federated-report@1"
LOCAL_SCHEMA = "codebase-source-federated-client@1"
OPTIMIZER_POLICY = "aggregate_fresh_adam_zero_moments_and_progress@1"
_FALSE = dict(source._FALSE)
_require, _wire = source._require, source._wire


def _adapter():
    return importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_codebase")


def _sync():
    return importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.codebase_federated_sync")


def _pins():
    files = {}
    for module in (__name__, _adapter().__name__, _sync().__name__):
        files[module] = hashlib.sha256(Path(importlib.import_module(module).__file__).read_bytes()).hexdigest()
    return {"source": source._pins(), "files": files,
            "scope": "listed_local_files_only_not_execution_attestation"}


@dataclass(frozen=True, slots=True)
class CodebaseFederatedClient:
    client_id: str
    paths: tuple[str, ...]

    def __post_init__(self):
        source._text(self.client_id, "client_id", 128)
        _require(type(self.paths) in {list, tuple} and 1 <= len(self.paths) <= 16,
                 "bounded nonempty client source paths required")
        for value in self.paths:
            source._text(value, "path", 1024)
            path = PurePosixPath(value)
            _require(not path.is_absolute() and path.as_posix() == value and ".." not in path.parts
                     and value.endswith(".py"), "canonical Python source path required")
        _require(len(set(self.paths)) == len(self.paths), "duplicate client source path")
        object.__setattr__(self, "paths", tuple(sorted(self.paths)))

    def to_dict(self):
        return {"client_id": self.client_id, "paths": list(self.paths)}


@dataclass(frozen=True, slots=True)
class CodebaseFederatedTrainingRecord:
    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self):
        _require(type(self._payload) is bytes and type(self.observed_live) is bool, "immutable federated record required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid
                 and value["schema"] == SCHEMA and value["authority"] == _FALSE
                 and all(flag is False for flag in value["authority"].values()), "federated record identity/authority differs")

    def to_dict(self):
        return json.loads(self._payload)


def _round(value):
    fields = FederatedRound.__dataclass_fields__
    result = FederatedRound(**{key: value[key] for key in fields if key not in {"parameters", "clients"}},
        parameters=tuple(ParameterSpec(row["name"], tuple(row["shape"]), row["dtype"]) for row in value["parameters"]),
        clients=tuple(ClientSpec(**row) for row in value["clients"]))
    _require(result.manifest == value, "closed canonical native federated round required")
    return result


def _clients(clients, selections):
    _require(type(clients) in {list, tuple} and 2 <= len(clients) <= 8
             and all(type(item) is CodebaseFederatedClient for item in clients), "two to eight native clients required")
    result = sorted((CodebaseFederatedClient(item.client_id, item.paths) for item in clients), key=lambda item: item.client_id)
    _require(len({item.client_id for item in result}) == len(result), "duplicate federated client identity")
    paths = [path for item in result for path in item.paths]
    _require(len(paths) == len(set(paths)) and set(paths) == {item.path for item in selections if item.role == "train"},
             "clients must partition all inherited training paths exactly once")
    return result


def _runtime(saved):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
    return runtimes.open_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        contract=ModalityContract.from_dict(saved["contract"]), feature_space=saved["feature_space"], state=saved["state"])


def _parent(index, registry, version_id, limits, seen=None):
    seen = set() if seen is None else seen
    _require(version_id not in seen and len(seen) < limits.max_ancestry, "cyclic or oversized federation ancestry")
    seen.add(version_id)
    row, saved = source._read_candidate(registry, version_id, limits)
    if "codebase_federation" not in saved["report"]:
        chain = source._lineage(index, registry, version_id, limits)
        provenance = chain[0][2]
        history = [*provenance["ancestral_training"], *(source._identity(target) for target in chain[0][3])]
        return {"row": row, "saved": saved, "origin_version_id": version_id,
                "origin": provenance, "tune": chain[0][4], "canary": chain[0][5], "replay": chain[0][6],
                "history": history, "depth": len(chain), "bytes": sum(item[0]["artifact"]["bytes"] for item in chain)}
    report = saved["report"]["codebase_federation"]
    expected = {"schema", "origin_version_id", "round", "head", "configuration", "clients", "implementation",
                "evaluation", "optimizer_policy", "base_state_sha256", "candidate_sha256", "aggregation", *_FALSE}
    _require(type(report) is dict and set(report) == expected and report["schema"] == REPORT_SCHEMA
             and all(report[key] is False for key in _FALSE) and report["implementation"] == _pins()
             and report["optimizer_policy"] == OPTIMIZER_POLICY, "closed federated producer/policy/authority required")
    base = _parent(index, registry, row["parent_version_id"], limits, seen)
    _require(base["depth"] + 1 <= limits.max_ancestry and base["bytes"] + row["artifact"]["bytes"] <= limits.max_ancestry_bytes,
             "federated ancestry exceeds bounds")
    adapter = _adapter().CodebaseFeatureCheckpoint.from_runtime(_runtime(base["saved"]),
        base_sha256=base["row"]["artifact"]["sha256"], base_version_id=base["row"]["version_id"])
    round_spec = adapter.validate_round(_round(report["round"]))
    _require(report["origin_version_id"] == base["origin_version_id"]
             and round_spec.lineage_id == "codebase-source:" + base["origin_version_id"]
             and report["base_state_sha256"] == features.digest(base["saved"]["state"]), "federated origin/parent differs")
    head = CodebaseHead.from_dict(report["head"])
    configuration = _configuration(**report["configuration"])
    _require(round_spec.max_local_steps == configuration["epochs"], "local step budget differs")
    selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
    declared = [CodebaseFederatedClient(item["local_payload"]["client_id"],
                                      tuple(row["path"] for row in item["local_payload"]["selections"])) for item in report["clients"]]
    declared = _clients(declared, selections)
    payloads, current_targets = _capture(index, head, base, declared, configuration, limits)
    _require(len(report["clients"]) == len(round_spec.clients) and
             [item["local_payload"] for item in report["clients"]] == payloads,
             "captured source/client inventory differs")
    updates, retained = [], 0
    metadata = row["metadata"]
    _require(type(metadata) is dict and set(metadata) == {"producer_run", "attempt", "result"}, "native federated metadata required")
    completion = registry.get_run_completion(metadata["producer_run"])
    _require(completion is not None and completion["candidate_version"] == row
             and completion["run"]["spec"] == {"schema": "autoencoder-federated-registry-run/v1",
                 "round_sha256": round_spec.round_sha256, "round": round_spec.manifest}
             and completion["run"]["base_version_id"] == base["row"]["version_id"]
             and metadata["attempt"] == completion["run"]["attempt"], "native federation completion belongs to another round")
    for item, approved, payload in zip(report["clients"], round_spec.clients, payloads):
        _require(type(item) is dict and set(item) == {"local_payload", "local_state", "training_report", "worker_receipt",
                    "work_binding", "update_artifact", "update_cid"}, "closed local candidate record required")
        _require(approved.client_id == payload["client_id"] and approved.sample_count == payload["sample_count"]
                 and approved.local_data_sha256 == features.digest(payload), "approved local source/count digest differs")
        work = _sync().CodebaseFederatedWorkBinding.from_dict(item["work_binding"])
        work.validate_round(round_spec)
        lease = completion["run"]["lease"]
        expected_work = _sync().bind_codebase_federated_work(round_spec,
            base_version_id=base["row"]["version_id"], source_head=head, client_id=approved.client_id,
            local_target_sha256=approved.local_data_sha256, sample_count=approved.sample_count,
            attempt=lease["attempt"], fence=lease["fence"])
        _require(work.to_dict() == expected_work.to_dict(), "native work lease/source binding differs")
        attempted = _local_report(item, payload, adapter, base, limits)
        derived = adapter.build_update(round_spec, approved.client_id, item["local_state"], local_steps=attempted)
        artifact = item["update_artifact"]
        _require(artifact["bytes"] <= limits.max_candidate_bytes, "binary update exceeds admitted bounds")
        registry.verify_artifact(artifact)
        retained += artifact["bytes"]
        update = read_client_update(registry.artifact_path(artifact), round_spec,
            expected_sha256=artifact["sha256"], expected_cidv1=item["update_cid"], max_bytes=limits.max_candidate_bytes)
        _require(update.update_sha256 == derived.update_sha256, "stored delta differs from local state and exact parent")
        updates.append(update)
    _require(retained + row["artifact"]["bytes"] <= limits.max_candidate_bytes, "retained round artifact bound exceeded")
    _require(base["bytes"] + row["artifact"]["bytes"] + retained <= limits.max_ancestry_bytes,
             "retained federation ancestry bytes exceed bound")
    candidate = aggregate_round(round_spec, adapter.parameters, updates)
    _require(saved["state"] == adapter.materialize_state(round_spec, candidate)
             and report["candidate_sha256"] == candidate.candidate_sha256
             and report["aggregation"] == candidate.provenance
             and saved["contract"] == base["saved"]["contract"]
             and saved["feature_space"] == base["saved"]["feature_space"], "aggregate state/layout/reduction differs")
    expected_result = {"schema": "autoencoder-federated-registry-result/v1", "candidate_sha256": candidate.candidate_sha256,
        "aggregation": candidate.provenance, "materialization_verified": True, "admitted": False,
        "qualified": False, "promotion_performed": False, "publication_performed": False}
    _require(metadata["result"] == expected_result and completion["run"]["result"] == expected_result
             and all(metadata["result"][key] is False for key in ("admitted", "qualified", "promotion_performed", "publication_performed")),
             "native aggregate materialization result differs")
    _evaluation(report["evaluation"], base, saved["state"], limits)
    _require(set(saved["report"]) == {"codebase_federation", *features.FALSE}
             and all(saved["report"][key] is False for key in features.FALSE), "aggregate outer report authority differs")
    return {**base, "row": row, "saved": saved, "head": head, "depth": base["depth"] + 1,
            "bytes": base["bytes"] + row["artifact"]["bytes"] + retained,
            "history": [*base["history"], *(source._identity(target) for target in current_targets)]}


def _configuration(epochs=1, learning_rate=.002, seed=1729):
    import math
    _require(type(epochs) is int and 1 <= epochs <= 32 and type(seed) is int and 0 <= seed < 2**31
             and type(learning_rate) in {int, float} and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "bounded exact federation configuration required")
    return {"epochs": epochs, "learning_rate": float(learning_rate), "seed": seed}


def _capture(index, head, base, clients, configuration, limits):
    _require(head.repository_id == base["origin"]["head"]["repository_id"], "foreign source repository lineage")
    selected = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
    targets, train = {}, []
    for selection in selected:
        target = source._targets_adapter().prepare_codebase_targets(index, expected_head=head,
            path=selection.path, contracts=selection.contracts)
        _require(target.ready_for_training, "unsupported selected source feature target")
        targets[selection.path] = target
        if selection.role == "train":
            train.append(target)
    for role, fixed in (("tune", base["tune"]), ("canary", base["canary"])):
        current = [targets[item.path] for item in selected if item.role == role]
        _require([source._identity(item) for item in current] == [source._identity(item) for item in fixed]
                 and [item.to_dict()["projections"] for item in current] == [item.to_dict()["projections"] for item in fixed],
                 "fixed evaluation source/features changed; start a new lineage")
    train = source._batch(train, limits)
    source._split_check(train, base["tune"], base["canary"], base["history"])
    _require(len({source._binding(item)["content_sha256"] for item in train}) == len(train),
             "duplicate current source content across clients")
    payloads = []
    for client in clients:
        chosen = [item for item in selected if item.path in client.paths]
        payloads.append({"schema": LOCAL_SCHEMA, "client_id": client.client_id, "head": head.to_dict(),
            "selections": [item.to_dict() for item in chosen],
            "training_targets": [targets[item.path].to_dict() for item in chosen], "sample_count": len(chosen),
            "tuning_targets_sha256": features.digest([item.to_dict() for item in base["tune"]]),
            "configuration": configuration, "implementation": _pins()})
    _require(sum(len(_wire(item)) for item in payloads) <= limits.max_target_bytes, "local source inventories exceed byte bound")
    return payloads, train


def _local_report(item, payload, adapter, base, limits):
    report = item["training_report"]
    attempted = report["attempted_epochs"]
    _require(type(attempted) is int and 1 <= attempted <= payload["configuration"]["epochs"],
             "local worker did not perform an admitted optimizer step")
    _require(type(report["epochs"]) is list and len(report["epochs"]) == attempted
             and [row["epoch"] for row in report["epochs"]] == list(range(1, attempted + 1))
             and all(report.get(key) is False for key in _FALSE if key in report),
             "local attempted-step inventory or authority differs")
    _require(report["schema"] == "native-projection-feature-training/v1"
             and report["contract_sha256"] == adapter.contract.sha256
             and report["feature_space_sha256"] == features.digest(adapter.feature_space)
             and report["base_state_sha256"] == features.digest(base["saved"]["state"])
             and report["training_targets_sha256"] == features.digest(payload["training_targets"])
             and report["tuning_targets_sha256"] == payload["tuning_targets_sha256"]
             and report["training_target_count"] == payload["sample_count"]
             and report["selected_total_epochs"] == item["local_state"]["completed_epochs"]
             and all(report.get(key) is False for key in features.FALSE)
             and all(report["configuration"][key] == value for key, value in payload["configuration"].items()),
             "local numerical report source/parent/count/configuration differs")
    _worker_receipt(item["worker_receipt"], limits)
    _require(len(_wire(item)) <= limits.max_candidate_bytes, "local candidate exceeds retained byte bound")
    return attempted


def _worker_receipt(receipt, limits):
    expected = {"executable_sha256", "worker_sha256", "input_sha256", "output_sha256", "elapsed_ms",
                "returncode", "workspace_cleaned", "limits", "memory_enforcement", "source_execution_attested"}
    _require(type(receipt) is dict and set(receipt) == expected
             and receipt["source_execution_attested"] is False and type(receipt["returncode"]) is int
             and receipt["returncode"] == 0 and receipt["workspace_cleaned"] is True
             and type(receipt["elapsed_ms"]) is int and receipt["elapsed_ms"] >= 0
             and receipt["memory_enforcement"] == "sampled_process_tree_rss_with_possible_overshoot"
             and all(type(receipt[key]) is str and re.fullmatch(r"[0-9a-f]{64}", receipt[key])
                     for key in ("executable_sha256", "worker_sha256", "input_sha256", "output_sha256"))
             and receipt["worker_sha256"] == source._pins()["files"][
                 "ipfs_datasets_py.optimizers.logic_theorem_optimizer.codebase_feature_worker"],
             "closed native worker receipt differs")
    bounds = receipt["limits"]
    _require(type(bounds) is dict and set(bounds) == {"resident_memory_bytes", "max_output_bytes"}
             and type(bounds["resident_memory_bytes"]) is int and bounds["resident_memory_bytes"] >= 512 * 1024 * 1024
             and type(bounds["max_output_bytes"]) is int and 0 < bounds["max_output_bytes"] <= limits.max_candidate_bytes,
             "native worker receipt bounds differ")


def _evaluation(value, base, state, limits=None):
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(value) is dict and set(value) == {"baseline", "aggregate", "purpose", "used_for_selection"}
             and value["purpose"] == "post_aggregation_fixed_canary_and_replay_diagnostics_not_qualification"
             and value["used_for_selection"] is False, "aggregate evaluation authority/selection differs")
    for name, numerical in (("baseline", base["saved"]["state"]), ("aggregate", state)):
        _require(type(value[name]) is dict and set(value[name]) == {"canary", "replay", "worker_receipt"},
                 "closed aggregate comparison required")
        for role in ("canary", "replay"):
            source._diagnostic(value[name][role], base[role], numerical,
                               numerical["contract_sha256"], base["saved"]["feature_space"])
        _worker_receipt(value[name]["worker_receipt"], limits)


def _evaluate(runtime, base, *, remaining, memory_mb, limits, signal, lease):
    joined = [*base["canary"], *base["replay"]]
    result, receipt = source._worker(runtime, joined, [], [], [], action="infer", epochs=1,
        learning_rate=runtime.state["optimizer_config"]["learning_rate"], seed=0,
        remaining=remaining, memory_mb=memory_mb, limits=limits, signal=signal, lease=lease)
    _require(result["training_executed"] is False and result["proof_authority"] is False,
             "aggregate evaluation attempted training or authority")
    inference = result["inference"]
    output, offset = {"worker_receipt": receipt}, 0
    for role in ("canary", "replay"):
        targets = base[role]
        vectors, ids, coverage = features._matrix(runtime.feature_space, targets)
        rows = inference["rows"][offset:offset + len(targets)]
        offset += len(targets)
        losses = []
        for vector, row in zip(vectors, rows):
            decoded = [value for name in runtime.feature_space["projection_ids"]
                       for value in row["reconstructed_projection_features"][name]]
            losses.append(sum((left - right) ** 2 for left, right in zip(vector, decoded)) / len(vector))
        output[role] = {"source_digests": ids, "mean_squared_errors": losses,
            "mean_squared_error": sum(losses) / len(losses), "coverage": coverage,
            "inference": {**inference, "rows": rows, "coverage": coverage},
            "used_for_selection": False, "semantic_or_property_evaluation": False}
    return output


def _record(index, registry, version_id, limits):
    source._native_owners(index, registry)
    base = _parent(index, registry, version_id, limits)
    _require("codebase_federation" in base["saved"]["report"], "registered federated candidate required")
    report = base["saved"]["report"]["codebase_federation"]
    value = {"schema": SCHEMA, "version_id": version_id, "variant_id": base["row"]["variant_id"],
        "parent_version_id": base["row"]["parent_version_id"], "origin_version_id": base["origin_version_id"],
        "head": report["head"], "round_sha256": _round(report["round"]).round_sha256,
        "registry_artifact": base["row"]["artifact"], "checkpoint_raw_cid": cid_for_bytes(_wire(base["saved"])),
        "state_sha256": features.digest(base["saved"]["state"]), "report_json": _wire(report).decode(),
        "authority": dict(_FALSE)}
    raw = canonical_dag_json_bytes(value)
    return CodebaseFederatedTrainingRecord(cid_for_structured(value), raw)


def load_codebase_federated_training(index, registry, version_id, *, limits=None):
    """Replay binary updates, numerical diagnostics and history; no fitting/writes."""
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is source.CodebaseFeatureTrainingLimits, "native federation bounds required")
    record = _record(index, registry, version_id, limits)
    _require(index.artifacts.get(record.artifact_cid) == record.to_dict(), "published federation metadata differs")
    return record


def recover_codebase_federated_training(index, registry, version_id, *, limits=None):
    """Explicitly republish derived provenance after a durable native completion.

    Replays historical source, binary updates and owner completion. It performs
    no fitting or current-source observation and returns observed_live=False.
    Ordinary historical loads never invoke this publication operation.
    """
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is source.CodebaseFeatureTrainingLimits, "native federation bounds required")
    record = _record(index, registry, version_id, limits)
    _require(index.artifacts.put(record.to_dict()) == record.artifact_cid, "recovered federation publication identity differs")
    return record


def train_current_codebase_federated_round(index, repository, *, expected_head, registry, base_version_id,
        clients, operation_id, epochs=1, learning_rate=.002, seed=1729, mode=TrainingMode.FEDERATED,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Train private same-parent clients and register one evaluated aggregate, never promote.

    Clients partition this repository's inherited training paths exactly once.
    Counts mean actual source-target envelopes; original replay is diagnostic
    only. Local selection uses fixed original tuning. Aggregate evaluation is
    independent numerical execution, not semantic qualification or selection.
    """
    _require(type(mode) is TrainingMode, "explicit native training mode required")
    if mode is not TrainingMode.FEDERATED:
        raise GradientBackendUnavailable("CodebaseIR round executor implements federation; synchronized-gradient execution is unavailable")
    source._native_owners(index, registry)
    source._text(operation_id, "operation_id", 128)
    _require(re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is source.CodebaseFeatureTrainingLimits, "native federation bounds required")
    configuration = _configuration(epochs, learning_rate, seed)
    with source._resources(index, repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (lease, signal, remaining, observe):
        base = _parent(index, registry, base_version_id, limits)
        _require(base["depth"] < limits.max_ancestry, "prospective federation ancestry depth exceeded")
        adapter = _adapter().CodebaseFeatureCheckpoint.from_runtime(_runtime(base["saved"]),
            base_sha256=base["row"]["artifact"]["sha256"], base_version_id=base_version_id)
        _require(adapter.state["optimizer_config"]["learning_rate"] == configuration["learning_rate"],
                 "private Adam resume requires the parent learning rate")
        selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
        clients = _clients(clients, selections)
        pins = _pins()
        payloads, _ = _capture(index, expected_head, base, clients, configuration, limits)
        round_spec = adapter.build_round("codebase-fed:" + operation_id, "codebase-source:" + base["origin_version_id"],
            tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads),
            max_local_steps=epochs)
        run_id = "codebase-fed:" + operation_id
        create_federated_run(registry, "codebase-fed-create:" + operation_id, run_id, base_version_id, round_spec)
        completed = registry.get_run_completion(run_id)
        if completed is not None:
            record = _record(index, registry, completed["candidate_version"]["version_id"], limits)
            index.artifacts.put(json.loads(record._payload))
            observe()
            return CodebaseFederatedTrainingRecord(record.artifact_cid, record._payload, True)
        invocation = uuid.uuid4().hex
        run_lease = registry.claim_run("codebase-fed-claim:" + operation_id + ":" + invocation,
            run_id, "codebase-fed-worker:" + invocation, lease_seconds=remaining() + 5.0)["lease"]
        try:
            updates, local = [], []
            with tempfile.TemporaryDirectory(prefix="codebase-federated-", dir=registry.artifact_root) as workspace:
                for position, (payload, client) in enumerate(zip(payloads, round_spec.clients)):
                    observe()
                    work = _sync().bind_codebase_federated_work(round_spec, base_version_id=base_version_id,
                        source_head=expected_head, client_id=client.client_id,
                        local_target_sha256=client.local_data_sha256, sample_count=client.sample_count,
                        attempt=run_lease["attempt"], fence=run_lease["fence"])
                    _sync().create_codebase_sync_controller(work)
                    targets = source._batch(payload["training_targets"], limits)
                    result, receipt = source._worker(_runtime(base["saved"]), targets, base["tune"], base["canary"], base["replay"],
                        action="train", epochs=epochs, learning_rate=learning_rate, seed=seed, remaining=remaining,
                        memory_mb=memory_mb, limits=limits, signal=signal, lease=lease)
                    state, report = result["result"]["state"], result["result"]["report"]
                    item = {"local_payload": payload, "local_state": state, "training_report": report,
                            "worker_receipt": receipt, "work_binding": work.to_dict()}
                    attempted = _local_report(item, payload, adapter, base, limits)
                    update = adapter.build_update(round_spec, client.client_id, state, local_steps=attempted)
                    path = Path(workspace) / f"client-{position}.update.bin"
                    artifact = write_client_update(path, round_spec, update, max_bytes=limits.max_candidate_bytes)
                    staged = registry.stage_artifact(path, artifact["sha256"])
                    updates.append(read_client_update(registry.artifact_path(staged), round_spec,
                        expected_sha256=staged["sha256"], expected_cidv1=artifact["cidv1"], max_bytes=limits.max_candidate_bytes))
                    local.append({**item, "update_artifact": staged, "update_cid": artifact["cidv1"]})
                    _require(sum(len(_wire(row)) + row["update_artifact"]["bytes"] for row in local) <= limits.max_candidate_bytes,
                             "retained private clients exceed admitted bounds")
                    observe()
                candidate = aggregate_round(round_spec, adapter.parameters, updates)
                state = adapter.materialize_state(round_spec, candidate)
                materialized = {"contract": base["saved"]["contract"], "feature_space": base["saved"]["feature_space"], "state": state}
                comparison = {"baseline": _evaluate(_runtime(base["saved"]), base, remaining=remaining,
                    memory_mb=memory_mb, limits=limits, signal=signal, lease=lease),
                    "aggregate": _evaluate(_runtime(materialized), base, remaining=remaining,
                    memory_mb=memory_mb, limits=limits, signal=signal, lease=lease),
                    "purpose": "post_aggregation_fixed_canary_and_replay_diagnostics_not_qualification", "used_for_selection": False}
                _evaluation(comparison, base, state, limits)
                report = {"schema": REPORT_SCHEMA, "origin_version_id": base["origin_version_id"],
                    "round": round_spec.manifest, "head": expected_head.to_dict(), "configuration": configuration,
                    "clients": local, "implementation": pins, "evaluation": comparison, "optimizer_policy": OPTIMIZER_POLICY,
                    "base_state_sha256": features.digest(base["saved"]["state"]), "candidate_sha256": candidate.candidate_sha256,
                    "aggregation": candidate.provenance, **_FALSE}
                materialized["report"] = {"codebase_federation": report, **features.FALSE}
                raw = _wire(materialized)
                update_bytes = sum(item["update_artifact"]["bytes"] for item in local)
                _require(len(raw) + update_bytes <= limits.max_candidate_bytes
                         and base["bytes"] + len(raw) + update_bytes <= limits.max_ancestry_bytes,
                         "prospective aggregate and retained update bytes exceed bounds")
                _require(_pins() == pins, "federation producer changed during execution")
                observe()
                path = Path(workspace) / "aggregate.checkpoint.json"
                path.write_bytes(raw)
                def verify_checkpoint(verified_round, verified_candidate, stored):
                    return (verified_round.manifest == round_spec.manifest
                            and verified_candidate.candidate_sha256 == candidate.candidate_sha256
                            and stored.read_bytes() == raw
                            and json.loads(stored.read_bytes())["state"] == adapter.materialize_state(verified_round, verified_candidate))
                completed = complete_federated_run(registry, "codebase-fed-complete:" + operation_id,
                    run_lease, round_spec, adapter.parameters, updates, path, verify_checkpoint=verify_checkpoint)
                run_lease = None
            observe()
            record = _record(index, registry, completed["version_id"], limits)
            _require(index.artifacts.put(json.loads(record._payload)) == record.artifact_cid, "federation publication identity differs")
            remaining()
            return CodebaseFederatedTrainingRecord(record.artifact_cid, record._payload, True)
        except BaseException as error:
            if run_lease is not None:
                try:
                    registry.fail_run("codebase-fed-fail:" + operation_id + ":" + str(run_lease["attempt"]), run_lease,
                        {"admitted": False, "qualified": False, "promotion_performed": False, "reason": "source_federation_incomplete"})
                except Exception as cleanup_error:
                    error.add_note("Native federation failure recording also failed: " + str(cleanup_error))
            raise


def infer_current_codebase_federated_features(index, repository, *, expected_head, registry, version_id, paths,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is source.CodebaseFeatureTrainingLimits, "native federation bounds required")
    with source._resources(index, repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (lease, signal, remaining, observe):
        record = load_codebase_federated_training(index, registry, version_id, limits=limits)
        _require(record.to_dict()["head"] == expected_head.to_dict(), "federated model belongs to another complete source head")
        base = _parent(index, registry, version_id, limits)
        selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
        _require(type(paths) in {tuple, list} and paths and len(set(paths)) == len(paths)
                 and set(paths) <= {item.path for item in selections}, "registered source cohort paths required")
        targets = [source._targets_adapter().prepare_codebase_targets(index, expected_head=expected_head,
            path=item.path, contracts=item.contracts) for item in selections if item.path in paths]
        result, receipt = source._worker(_runtime(base["saved"]), targets, [], [], [], action="infer", epochs=1,
            learning_rate=base["saved"]["state"]["optimizer_config"]["learning_rate"], seed=0,
            remaining=remaining, memory_mb=memory_mb, limits=limits, signal=signal, lease=lease)
        _require(result["training_executed"] is False and result["proof_authority"] is False, "inference worker authority differs")
        observe()
        return {"version_id": version_id, "head": expected_head.to_dict(), "inference": result["inference"],
                "worker_receipt": receipt, "training_executed": False, **_FALSE}

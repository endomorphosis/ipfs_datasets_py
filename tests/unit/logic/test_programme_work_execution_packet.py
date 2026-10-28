"""Normally imported metadata packets preserve supplied custody and no authority.

These authored controls execute no model, native task source or subprocess.
Physical snapshot authentication and actual dispatch remain separate callers.
"""
from copy import deepcopy
import builtins
import json
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
    prepare_programme_work_packet_v1,
)


TASKS = (
    ("LIRAE-LIR03-SOURCE-PACKET-01", "source_cache_lineage", "LIR-02"),
    ("LIRAE-LIR03-IR-PACKET-01", "typed_ir_scoped_graph", "LIR-07"),
    ("LIRAE-LIR03-MODEL-PACKET-01", "model_compatibility_quality", "LIR-17"),
    ("LIRAE-LIR03-LEAN-PACKET-02", "lean_release_verification", "LIR-12"),
)
ROLE_GATES = (
    "physical_occurrence_crosswalk", "graph_dependency_closure",
    "producer_head_compatibility", "lean_import_toolchain_closure",
)
FALSE_FLAGS = (
    "descriptor_hashes_verified", "current_parent_row_verified",
    "current_source_epoch_verified", "native_status_verified", "capability_verified",
    "independently_verified", "dispatch_authorized", "mutation_authorized",
    "native_admission", "model_execution_authorized", "training_authorized",
    "parent_semantic_admission", "task_completion_authority", "goal_completion_authority",
    "completion_authority", "admitted", "formalized", "semantic_review_verified",
)


def _ref(path, *, size=123, digest="a" * 64):
    return {"path": path, "bytes": size, "sha256": digest}


def _request(index=0):
    task_id, _, parent = TASKS[index]
    return {
        "task_id": task_id,
        "parent_reference": {
            "repository": "ipfs_datasets_py", "revision": "1" * 40,
            "path": "ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json",
            "task_id": parent, "task_sha256": "2" * 64,
        },
        "current_parent_reference": {
            "backlog": _ref("workspace/test-logs/programme/input-snapshots-v01/BACKLOG.json"),
            "task_id": parent, "task_sha256": "3" * 64,
        },
        "authority_binding": {
            "kind": "legacy_markdown", "namespace": "legal-ir-autoencoder-v1",
            "board": _ref("workspace/test-logs/programme/input-snapshots-v01/LIRAE-TODO.md"),
            "plan": _ref("workspace/test-logs/programme/input-snapshots-v01/plan.json"),
            "source_control_revision": "4" * 64,
        },
        "owner_sources": [_ref(
            "workspace/test-logs/programme/input-snapshots-v01/owners/"
            "ipfs_datasets_py/logic/autoformal/owner.py")],
        "evidence": [_ref("workspace/test-logs/programme/input-snapshots-v01/closed-review.json")],
        "remaining_gates": ["original_owner_admission", "independent_acceptance", ROLE_GATES[index]],
    }


@pytest.mark.parametrize("index", (0, 1, 2, 3), ids=("source", "ir", "model", "lean"))
def test_each_fixed_task_derives_its_parent_commands_scope_and_budget(index):
    request = _request(index)
    before = deepcopy(request)
    packet = prepare_programme_work_packet_v1(**request)
    task_id, role, parent = TASKS[index]
    assert packet["schema"] == "programme-work-execution-packet/v1"
    assert (packet["task_id"], packet["role"], packet["parent_task_id"]) == (task_id, role, parent)
    assert packet["metadata_complete"] is True
    assert packet["snapshot_binding_only"] is True
    assert packet["readiness"] == "original_admission_required"
    assert packet["execution_kind"] == "control_metadata_only"
    script = "scripts/ops/legal_ir/legal_ir_supervisor_contract.py"
    assert packet["validation_argv"] == [
        ["python3", script, "--materialize-programme-preparation", task_id],
        ["python3", script, "--check-task", task_id],
    ]
    env = "IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. "
    assert packet["validation_commands"] == [
        env + "python3 " + script + " --materialize-programme-preparation " + task_id
        + " && " + env + "python3 " + script + " --check-task " + task_id]
    directory = "docs/implementation/reports/evidence/legal_ir_autoencoder/" + task_id.lower()
    assert packet["outputs"] == packet["allowed_paths"] == [directory + "/packet.json", directory + "/receipt.json"]
    assert packet["code_allowlist"] == packet["test_allowlist"] == []
    assert packet["exclusive_keys"] == ["programme-preparation:" + task_id]
    assert packet["budgets"] == dict(wall_seconds=300, cpu_slots=1, memory_mb=1024,
                                    storage_bytes=16777216, child_process_slots=1, max_attempts=1)
    assert all(packet[key] is False for key in FALSE_FLAGS)
    assert packet["supervision_masks"] == {"training": 0, "evaluation_gold": 0}
    assert request == before
    assert json.loads(json.dumps(packet, allow_nan=False)) == packet


def test_packet_is_detached_without_collapsing_original_and_snapshot_parent_hashes():
    request = _request()
    packet = prepare_programme_work_packet_v1(**request)
    assert packet["parent_reference"]["task_sha256"] == "2" * 64
    assert packet["current_parent_reference"]["task_sha256"] == "3" * 64
    request["owner_sources"][0]["sha256"] = "b" * 64
    request["authority_binding"]["board"]["sha256"] = "c" * 64
    request["remaining_gates"].append("source_custody")
    assert packet["owner_sources"][0]["sha256"] == "a" * 64
    assert packet["authority_binding"]["board"]["sha256"] == "a" * 64
    assert "source_custody" not in packet["remaining_gates"]
    packet["evidence"][0]["sha256"] = "d" * 64
    assert request["evidence"][0]["sha256"] == "a" * 64


def test_unopened_snapshots_remain_unverified_without_imports_io_or_subprocess(monkeypatch):
    request = _request()
    events = []

    def forbidden(*args, **kwargs):
        events.append("unexpected effect")
        raise AssertionError("pure packet preparation attempted an effect")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(Path, "read_bytes", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(Path, "open", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(builtins, "__import__", forbidden)
        packet = prepare_programme_work_packet_v1(**request)
    assert not events
    assert packet["descriptor_hashes_verified"] is False
    assert packet["current_parent_row_verified"] is False
    assert packet["native_status_verified"] is False
    assert packet["dispatch_authorized"] is False


@pytest.mark.parametrize("task_id", (
    "LIR-9001", "LIRAE-CONT-OCCURRENCE-VALIDATE-01", "LIRAE-LIR03-LEAN-PACKET-01",
    "LIRAE-LIR03-SOURCE-PACKET-01 && touch injected", True,
), ids=("native-handoff", "old-continuation", "unknown-successor", "shell-injection", "boolean"))
def test_unregistered_or_injected_task_ids_refuse(task_id):
    request = _request()
    request["task_id"] = task_id
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("part", ("parent_reference", "current_parent_reference"),
                         ids=("origin", "current-snapshot"))
def test_wrong_original_or_current_parent_is_not_reparented(part):
    request = _request()
    request[part]["task_id"] = "LIR-17"
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("damage", (
    "repository", "origin-path", "revision-length", "uppercase-task-hash",
    "current-backlog-suffix", "native-authority", "foreign-namespace", "control-revision",
), ids=("repository", "origin-path", "revision-length", "uppercase-task-hash",
        "current-backlog-suffix", "native-authority", "foreign-namespace", "control-revision"))
def test_source_epoch_and_authority_contracts_refuse_misbindings(damage):
    request = _request()
    if damage == "repository":
        request["parent_reference"]["repository"] = "ipfs_accelerate_py"
    elif damage == "origin-path":
        request["parent_reference"]["path"] = "other/BACKLOG.json"
    elif damage == "revision-length":
        request["parent_reference"]["revision"] = "1" * 39
    elif damage == "uppercase-task-hash":
        request["current_parent_reference"]["task_sha256"] = "A" * 64
    elif damage == "current-backlog-suffix":
        request["current_parent_reference"]["backlog"]["path"] = "snapshot/BACKLOG.bin"
    elif damage == "native-authority":
        request["authority_binding"]["kind"] = "native_catalogue"
    elif damage == "foreign-namespace":
        request["authority_binding"]["namespace"] = "legal-ir-span-graph-lean-refinement-20261016"
    else:
        request["authority_binding"]["source_control_revision"] = "4" * 40
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("part", (
    "parent_reference", "current_parent_reference", "authority_binding", "owner", "evidence",
), ids=("origin-parent", "snapshot-parent", "authority", "source-ref", "evidence-ref"))
def test_closed_schemas_reject_embedded_authority_and_input_roles(part):
    request = _request()
    target = (request["owner_sources"][0] if part == "owner" else
              request["evidence"][0] if part == "evidence" else request[part])
    target["admitted"] = True
    target["role"] = "checkpoint"
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("path", (
    "snapshot/../review.json", "./review.json", "snapshot//review.json",
    "snapshot/review*.json", "snapshot/review[0].json", "snapshot\\review.json",
    "snapshot/review\n.json", "snapshot/review\x00.json", "https://example/review.json",
    "snapshot/review.json ", "snapshot/review.json/", "snapshot/review.bin",
), ids=("parent-escape", "dot", "empty-component", "star", "glob", "backslash",
        "newline", "nul", "uri", "trailing-space", "trailing-slash", "wrong-suffix"))
def test_unsafe_descriptor_paths_refuse_before_any_file_access(path):
    request = _request()
    request["evidence"][0]["path"] = path
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("location", ("board", "plan", "backlog", "evidence"),
                         ids=("board-snapshot", "plan-snapshot", "backlog-snapshot", "metadata-evidence"))
def test_immutable_absolute_snapshot_paths_are_supported_as_declarations(location):
    request = _request()
    target = (request["authority_binding"][location] if location in {"board", "plan"} else
              request["current_parent_reference"]["backlog"] if location == "backlog" else
              request["evidence"][0])
    target["path"] = "/retained/immutable/" + target["path"].rsplit("/", 1)[-1]
    packet = prepare_programme_work_packet_v1(**request)
    assert packet["snapshot_binding_only"] is True
    assert all(packet[key] is False for key in FALSE_FLAGS)


def test_owner_snapshots_are_relative_source_data_and_not_live_import_targets():
    request = _request()
    packet = prepare_programme_work_packet_v1(**request)
    assert packet["owner_sources"][0]["path"].startswith("workspace/")
    request["owner_sources"][0]["path"] = "/retained/owner.py"
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("size", (True, -1, 8388609, 2 ** 63, 1.0, float("nan")),
                         ids=("boolean", "negative", "descriptor-cap", "integer-cap", "float", "nan"))
def test_descriptor_sizes_require_bounded_plain_integers(size):
    request = _request()
    request["evidence"][0]["bytes"] = size
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("list_name", ("owner_sources", "evidence"), ids=("sources", "evidence"))
def test_descriptor_populations_are_nonempty_unique_and_bounded(list_name):
    request = _request()
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**{**request, list_name: []})
    request[list_name].append(deepcopy(request[list_name][0]))
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)
    suffix = ".py" if list_name == "owner_sources" else ".json"
    request = _request()
    request[list_name] = [_ref("snapshot/" + str(i) + suffix) for i in range(64)]
    assert len(prepare_programme_work_packet_v1(**request)[list_name]) == 64
    request[list_name].append(_ref("snapshot/64" + suffix))
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("damage", ("unknown", "other-role", "duplicate", "missing-owner", "missing-review"),
                         ids=("unknown", "other-role", "duplicate", "missing-owner", "missing-review"))
def test_remaining_gates_keep_role_and_unresolved_independent_admission(damage):
    request = _request()
    if damage == "unknown":
        request["remaining_gates"].append("ready")
    elif damage == "other-role":
        request["remaining_gates"].append("native_preservation_and_build")
    elif damage == "duplicate":
        request["remaining_gates"].append("independent_acceptance")
    elif damage == "missing-owner":
        request["remaining_gates"].remove("original_owner_admission")
    else:
        request["remaining_gates"].remove("independent_acceptance")
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


@pytest.mark.parametrize("damage", ("utf8-bytes", "nodes", "depth", "serialized-bytes", "cyclic"),
                         ids=("utf8-bytes", "nodes", "depth", "serialized-bytes", "cyclic"))
def test_metadata_limits_fail_boundedly(damage):
    request = _request()
    if damage == "utf8-bytes":
        request["evidence"][0]["path"] = "é" * 512 + ".json"
    elif damage == "nodes":
        request["authority_binding"]["untrusted"] = list(range(2048))
    elif damage == "depth":
        nested = []
        for _ in range(10):
            nested = [nested]
        request["authority_binding"]["untrusted"] = nested
    elif damage == "serialized-bytes":
        request["authority_binding"]["untrusted"] = ["x" * 1024 for _ in range(400)]
    else:
        cycle = []
        cycle.append(cycle)
        request["authority_binding"]["untrusted"] = cycle
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


def test_exact_utf8_string_boundary_is_not_character_counted():
    request = _request()
    path = "x" + "é" * 509 + ".json"
    assert len(path.encode("utf-8")) == 1024
    request["evidence"][0]["path"] = path
    assert prepare_programme_work_packet_v1(**request)["evidence"][0]["path"] == path
    request["evidence"][0]["path"] = "y" + path
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)


def test_non_json_subclasses_and_callbacks_are_refused_without_invocation():
    events = []

    class HostileMapping(dict):
        def items(self):
            events.append("items")
            raise AssertionError("custom mapping was invoked")

    def callback():
        events.append("callback")
        raise AssertionError("callback was invoked")

    request = _request()
    request["authority_binding"] = HostileMapping(request["authority_binding"])
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)
    request = _request()
    request["evidence"][0]["sha256"] = callback
    with pytest.raises(ValueError):
        prepare_programme_work_packet_v1(**request)
    assert events == []


def test_callers_cannot_supply_commands_budgets_or_true_authority_arguments():
    request = _request()
    for key, value in (("argv", ["sh", "-c", "touch injected"]),
                       ("budgets", {"wall_seconds": 999999}), ("dispatch_authorized", True)):
        with pytest.raises(TypeError):
            prepare_programme_work_packet_v1(**request, **{key: value})

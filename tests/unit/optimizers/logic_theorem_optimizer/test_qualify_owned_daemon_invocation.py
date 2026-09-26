"""Bounded qualification-harness checks; no native daemon or owner dispatch."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/ops/legal_ir/qualify_owned_daemon_invocation.py"
spec = importlib.util.spec_from_file_location("_test_owned_qualification", SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
helper = harness.load_helper()


def inputs():
    summary = {
        "snapshot_evaluation_enabled": True, "snapshot_shutdown": {"drained": True},
        "snapshot_evaluator": {"closed": True, "worker_alive": False, "published_snapshots": 1,
            "completed_evaluations": 1, "failed_evaluations": 0, "rejected_result_count": 0},
        "latest_published_snapshot": {"versions": {"state": "bound"}, "sequence": 1},
        "latest_promoted_snapshot_evaluation": {"versions": {"state": "bound"}, "sequence": 1},
        "latest_promoted_snapshot_complete": True,
    }
    memory = {"evaluation_passes": [
        {"phase": "before_train_evaluation", "use_sample_memory": True},
        {"phase": "before_validation_evaluation", "use_sample_memory": False},
        {"phase": "before_after_train_evaluation", "use_sample_memory": True},
        {"phase": "before_after_validation_evaluation", "use_sample_memory": False}],
        "projection_report_sample_memory_used": False}
    native = {"success": True, "native_exit_code": 0, "summary": summary,
        "sample_memory_policy": memory, "callable_replacements": [],
        "network_guard": {"socket_denial_verified": True}, "runtime_guards": {"bound": True}}
    independent = {"success": True, "evaluation_matches_final": True,
        "sample_memory_policy": deepcopy(memory), "network_guard": {"socket_denial_verified": True},
        "runtime_guards": {"bound": True}}
    arguments = {key: ",".join(helper.BRIDGES) for key in (
        "bridge_loss_adapters", "autoencoder_metric_bridge_adapters", "autoencoder_diagnostic_bridge_adapters")}
    arguments.update(snapshot_evaluation_enabled=True, bridge_evaluate_provers=False,
        autoencoder_bridge_workers=1, max_sample_text_chars=0, autoencoder_metric_bridge_max_sample_text_chars=0)
    request = {"effective_arguments": arguments, "daemon_argv": [],
        "environment": {"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0"}}
    diagnostic = {"sample_count": 3, "evaluated_count": 15, "metric_failures": 0,
        "adapter_metrics_complete": True, "adapters": {name: {"sample_count": 3,
        "evaluated_count": 3, "metric_failures": 0} for name in helper.BRIDGES}}
    cycle = {name: {"legal_ir_target_count": 3} for name in helper.EVALUATIONS}
    cycle.update(train_indices=[0, 1, 2], validation_indices=[3, 4, 5],
        logic_bridge_train=deepcopy(diagnostic), logic_bridge_validation=deepcopy(diagnostic))
    walk = {"roles": {"train": [{"index": i} for i in range(3)],
        "validation": [{"index": i} for i in range(3, 6)]}}
    return native, independent, request, cycle, walk


def test_positive_checks_use_actual_observation_phase_names_and_default_async():
    checks, memory = harness.qualification_checks(helper, *inputs())
    assert all(checks.values())
    assert all(memory.values())


@pytest.mark.parametrize("case", ["zero_targets", "wrong_role", "missing_bridge", "failed_snapshot",
    "wrong_memory", "duplicate_pass", "missing_guard", "replaced_callable", "no_network_guard"])
def test_material_native_failures_cannot_pass(case):
    native, independent, request, cycle, walk = inputs()
    if case == "zero_targets":
        cycle[helper.EVALUATIONS[0]]["legal_ir_target_count"] = 0
    elif case == "wrong_role":
        cycle["train_indices"] = [0, 1, 3]
    elif case == "missing_bridge":
        del cycle["logic_bridge_train"]["adapters"][helper.BRIDGES[0]]
    elif case == "failed_snapshot":
        native["summary"]["snapshot_evaluator"]["failed_evaluations"] = 1
    elif case == "wrong_memory":
        native["sample_memory_policy"]["evaluation_passes"][0]["use_sample_memory"] = False
    elif case == "duplicate_pass":
        native["sample_memory_policy"]["evaluation_passes"].append(
            deepcopy(native["sample_memory_policy"]["evaluation_passes"][0]))
    elif case == "missing_guard":
        independent["runtime_guards"] = {}
    elif case == "replaced_callable":
        native["callable_replacements"] = ["evaluate"]
    else:
        independent["network_guard"]["socket_denial_verified"] = False
    checks, _ = harness.qualification_checks(helper, native, independent, request, cycle, walk)
    assert not all(checks.values())


def test_fixed_resource_scope_and_environment_does_not_import_credentials():
    policy = harness.resource_policy()
    assert policy["roots"] == [str(ROOT / "workspace/test-logs"), str(ROOT / "workspace/todo-queues"),
        str(ROOT / "docs/implementation/reports/evidence"), "/tmp/pytest-of-barberb"]
    assert (policy["storage_bytes"], policy["memory_mb"], policy["cpu_slots"]) == (1_000_000_000, 3072, 1)
    env = harness.parent_environment(helper, {"OPENAI_API_KEY": "omit", "PYTHONPATH": "/foreign",
        "IPFS_DATASETS_RESOURCE_SCHEDULER_PATH": "/tmp/shared.json"})
    assert "OPENAI_API_KEY" not in env
    assert env["PYTHONPATH"] == str(ROOT)
    assert env["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"] == "/tmp/shared.json"
    assert all(env[key] == value for key, value in helper.ENVIRONMENT.items())


def test_real_native_parser_accepts_fixed_argv_with_default_async(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
    for key, value in helper.ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    capsule = tmp_path / "descriptor-only.json"
    capsule.write_text("{}")
    argv = harness.daemon_argv(helper, helper.descriptor(capsule))
    configuration = contracts.effective_configuration(argv)
    assert configuration["run_id"] == "owner-leased-qualification"
    assert configuration["max_cycles"] == 1
    assert configuration["train_count"] == configuration["validation_count"] == 3
    assert configuration["snapshot_evaluation_enabled"] is True
    assert "--snapshot-evaluation-enabled" not in argv


def test_explicit_native_flag_required_before_loading_helper(monkeypatch):
    monkeypatch.setattr(harness, "load_helper", lambda: pytest.fail("must parse authorization first"))
    with pytest.raises(SystemExit) as raised:
        harness.main(["--directory", "/tmp/unused", "--output", "/tmp/unused.json"])
    assert raised.value.code == 2


def test_replay_inventory_reads_private_registry_without_mutation(tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    database = tmp_path / "private.duckdb"
    with AutoencoderRegistry(database, tmp_path / "artifacts"):
        pass
    before = harness.sha(database)
    inventory = harness.inspect_private_database(database, harness.RUN_ID)
    assert inventory["candidate_event_count"] == inventory["version_count"] == 0
    assert inventory["owner_generation"] == 1
    assert harness.sha(database) == before

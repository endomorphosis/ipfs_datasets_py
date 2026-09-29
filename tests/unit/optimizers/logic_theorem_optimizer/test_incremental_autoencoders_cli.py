"""Operator runner boundaries; optimizer semantics are tested by the worker."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("incremental_autoencoders_cli", ROOT / "scripts/ops/legal_ir/run_incremental_autoencoders.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_local_intake_deduplicates_and_ignores_file_append_for_record_identity(tmp_path):
    source = tmp_path / "samples.jsonl"
    a = {"title": "5", "section": "1", "text": "The agency shall retain records."}
    b = {"title": "5", "section": "2", "text": "The agency shall submit a report."}
    source.write_text(json.dumps(a) + "\n" + json.dumps(a) + "\n")
    first = cli.local_records(source)
    assert len(first) == 1
    source.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n")
    second = cli.local_records(source)
    assert first[0]["record_id"] in {r["record_id"] for r in second}
    assert len(second) == 2


def test_templates_reuse_registered_baseline_and_preserve_source_evidence(tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    base = tmp_path / "base.json"
    base.write_text(ModalAutoencoderTrainingState().to_json())
    record = {"record_id": "sha256:" + "a" * 64, "sample": {
        "title": "5", "section": "1", "text": "The agency shall retain records."},
        "provenance": {"admitted": False, "original": "retained"}}
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "cas") as registry:
        opts = dict(state_directory=tmp_path, checkpoint=base,
                    source_hashes={key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")})
        first = cli.make_templates(registry, [record], **opts)[0]
        second = cli.make_templates(registry, [record], **opts)[0]
        assert first.canonical_sha256 == second.canonical_sha256
        assert first.training_config.legal_ir_bridge_names
        assert first.training_config.max_line_search_attempts == 1
        assert first.training_config.projection_max_update_families == 5
        assert first.training_config.use_sample_memory is False
        assert first.candidate_storage == "sparse"
        assert first.validation_samples == ()
        assert "projection_max_composed_refinement_attempts" not in first.to_dict()["training_config"]
        assert json.loads((tmp_path / "inputs" / ("a" * 64 + ".json")).read_bytes()) == record
        changed = {**record, "sample": {**record["sample"], "text": "Changed"}}
        with pytest.raises(ValueError, match="identity collision"):
            cli.make_templates(registry, [changed], **opts)


def test_templates_bind_validation_split_and_operator_requires_qualification(tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    base = tmp_path / "base.json"
    base.write_text(ModalAutoencoderTrainingState().to_json())
    train = {"record_id": "b" * 64, "sample": {"title": "5", "section": "1", "text": "The agency shall retain records."}}
    validation = {"record_id": "c" * 64, "sample": {"title": "5", "section": "2", "text": "The officer shall file reports."}}
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "cas") as registry:
        opts = dict(state_directory=tmp_path, checkpoint=base,
                    source_hashes={key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")})
        template = cli.make_templates(registry, [train], validation_records=[validation], **opts)[0]
        assert [row.text for row in template.samples] == [train["sample"]["text"]]
        assert [row.text for row in template.validation_samples] == [validation["sample"]["text"]]
        assert not {row.text for row in template.samples} & {row.text for row in template.validation_samples}
        assert template.split_snapshot_id.startswith("qualification-validation-")
        no_validation = cli.make_templates(registry, [train], **opts)[0]
        assert template.split_snapshot_id != no_validation.split_snapshot_id
        assert template.canonical_sha256 != no_validation.canonical_sha256
        assert template.samples == no_validation.samples
        refined = cli.make_templates(registry, [train], validation_records=[validation],
                                     composed_refinement_attempts=3, **opts)[0]
        assert refined.training_config.projection_max_composed_refinement_attempts == 3
        assert refined.canonical_sha256 != template.canonical_sha256
        assert refined.samples == template.samples and refined.validation_samples == template.validation_samples
    args = cli.parser().parse_args(["--state-directory", str(tmp_path), "--input-jsonl", "input"])
    assert args.max_training_rounds == 3 and args.lake_timeout_seconds == 120
    assert not hasattr(args, "disable_qualification")
    assert args.composed_refinement_attempts == 0


@pytest.mark.parametrize("extra", [[], ["--execution-mode", "inference", "--validation-jsonl", "validation"]])
def test_refinement_rejected_before_work_without_training_validation(tmp_path, extra):
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(tmp_path / "uncreated"), "--input-jsonl", "input",
                  "--composed-refinement-attempts", "1", *extra])
    assert not (tmp_path / "uncreated").exists()


def test_orchestration_binds_native_grammar_and_statement_lock():
    hashes = cli.orchestration_hashes()
    assert "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py" in hashes
    assert "ipfs_datasets_py/logic/parsers/legacy_modal.py" in hashes
    assert "ipfs_datasets_py/logic/modal/decompiler.py" in hashes
    assert "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_adaptive_optimizer.py" in hashes
    assert any(path.endswith("JevOps/jevops/statement_lock.py") for path in hashes)


def test_publication_network_failure_retries_without_training(tmp_path, monkeypatch):
    from ipfs_datasets_py.huggingface import autoencoder_incremental as publisher
    class Registry:
        pending = True
        def pending_outbox(self, destination, limit):
            assert destination == "huggingface" and limit == 16
            return [{"event_id": "qualified-update"}] if self.pending else []
    registry = Registry()
    calls = []
    def deliver(owner, event_id, *, upload, state_directory):
        calls.append(event_id)
        assert owner is registry and upload is True
        assert state_directory == tmp_path / "publication-deliveries"
        if len(calls) == 1:
            raise ConnectionError("sensitive HTTP body must not be copied")
        registry.pending = False
        return {"event_id": event_id, "uploaded": True, "acknowledged": True}
    monkeypatch.setattr(publisher, "deliver_sparse_update", deliver)
    first = cli.deliver_pending_updates(registry, tmp_path)
    assert first[0]["retry_pending"] and not first[0]["uploaded"]
    assert "sensitive" not in json.dumps(first)
    second = cli.deliver_pending_updates(registry, tmp_path)
    assert second[0]["acknowledged"]
    assert cli.deliver_pending_updates(registry, tmp_path) == []
    assert calls == ["qualified-update", "qualified-update"]


def test_completed_group_cleanup_kills_lingering_workers(monkeypatch):
    calls = []
    class Process:
        pid = 123
        def wait(self, timeout):
            calls.append(("wait", timeout))
    monkeypatch.setattr(cli.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    cli._stop_group(Process())
    assert (123, cli.signal.SIGTERM) in calls
    assert (123, cli.signal.SIGKILL) in calls


def test_omitted_workers_delegate_live_capacity_without_changing_logical_lanes(tmp_path, monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources

    snapshot = {"fixture": "current scheduler census"}
    class Scheduler:
        def snapshot(self):
            return snapshot

    def available(observed):
        assert observed is snapshot
        return {"cpu_slots": 5, "memory_mb": 8192, "child_process_slots": 9}

    plans, configs = [], []
    def plan(mode, **limits):
        plans.append((mode, limits))
        return {"workers": 0, "reason": "fixture capacity exhausted"}

    supervised = cli.supervised_cycle
    def cycle(config):
        configs.append(dict(config))
        return supervised(config)

    monkeypatch.setattr(cli, "_pin", lambda **_: {})
    monkeypatch.setattr(cli, "supervised_cycle", cycle)
    monkeypatch.setattr(scheduler, "get_global_resource_scheduler", lambda: Scheduler())
    monkeypatch.setattr(capacity, "scheduler_capacity", available)
    monkeypatch.setattr(capacity, "execution_capacity_plan", plan)
    monkeypatch.setattr(resources, "DaemonResourceReservation", lambda **_: pytest.fail("reserved without capacity"))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: pytest.fail("started work without capacity"))
    state = tmp_path / "automatic"
    ledger = tmp_path / "resources.json"
    assert cli.parser().get_default("workers") == cli.parser().get_default("parallel_workers") == 0
    assert cli.main(["--state-directory", str(state), "--input-jsonl", "source",
                     "--resource-ledger", str(ledger)]) == 0
    assert len(configs) == 1 and configs[0]["workers"] == 32 and configs[0]["parallel_workers"] == 0
    assert plans == [("training", {"max_workers": 32, "memory_budget_mb": 8192,
        "pending_count": 4, "scheduler_available_cpu": 5,
        "scheduler_available_memory_mb": 8192, "scheduler_available_process_slots": 9})]
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["deferred"] and receipt["training_executed"] is False
    assert not (state / "cycles").exists() and not ledger.exists()


@pytest.mark.parametrize("extra", [
    ["--workers", "33"], ["--shard-count", "2", "--shard-index", "2"],
    ["--max-seconds", "nan"], ["--storage-bytes", "50000000001"],
])
def test_bad_resource_or_topology_config_fails_before_work(tmp_path, extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["--state-directory", str(tmp_path), "--input-jsonl", str(tmp_path / "input"), *extra])
    assert error.value.code == 2


def test_execution_route_rejects_unknown_mode_before_intake(monkeypatch):
    monkeypatch.setattr(cli, "_pin", lambda **_: pytest.fail("unknown mode touched model sources"))
    with pytest.raises(ValueError, match="execution gate"):
        cli.run_cycle({"execution_mode": "evaluate-and-train"})


def test_inference_cli_rejects_publication_before_state_creation(tmp_path):
    state = tmp_path / "forbidden"
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(state), "--execution-mode", "inference",
                  "--input-jsonl", "source", "--validation-jsonl", "validation",
                  "--publish-repository", "justicedao/uscode-autoformal-span-cache"])
    assert not state.exists()


def test_auto_lanes_are_stable_while_dispatch_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_pin", lambda **_: {})
    configs = []
    def cycle(config):
        configs.append(dict(config))
        return {"deferred": True, "training_executed": False}
    monkeypatch.setattr(cli, "supervised_cycle", cycle)
    args = ["--state-directory", str(tmp_path / "auto"), "--input-jsonl", "source"]
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    assert [config["workers"] for config in configs] == [32, 32]
    with pytest.raises(SystemExit):
        cli.main([*args, "--execution-mode", "inference", "--validation-jsonl", "validation"])


def test_insufficient_group_memory_defers_before_creating_cycle_or_reservation(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    class Scheduler:
        def snapshot(self): return {}
    monkeypatch.setattr(scheduler, "get_global_resource_scheduler", lambda: Scheduler())
    monkeypatch.setattr(capacity, "scheduler_capacity", lambda _: {"cpu_slots": 8, "memory_mb": 1024, "child_process_slots": 8})
    monkeypatch.setattr(capacity, "capacity_plan", lambda **_: {"workers": 1})
    monkeypatch.setattr(resources, "DaemonResourceReservation", lambda **_: pytest.fail("unavailable reservation attempted"))
    state = tmp_path / "no-work"
    result = cli.supervised_cycle({"execution_mode": "training", "workers": 32,
        "memory_mb": 8192, "max_batches": 4, "state_directory": str(state)})
    assert result["deferred"] and result["training_executed"] is False
    assert not state.exists()


def test_reused_workers_require_explicit_opt_in_without_changing_logical_lanes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_pin", lambda **_: {})
    captured = []
    monkeypatch.setattr(cli, "supervised_cycle", lambda config: captured.append(config) or {"deferred": True})
    for extra, expected in (([], True), (["--fresh-training-workers"], True), (["--reuse-training-workers"], False)):
        assert cli.main(["--state-directory", str(tmp_path / str(expected)), "--input-jsonl", "source", *extra]) == 0
        assert captured[-1]["fresh_training_workers"] is expected
        assert captured[-1]["workers"] == 32
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--state-directory", str(tmp_path),
                                 "--fresh-training-workers", "--reuse-training-workers"])


def _selection_cycle_config(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    base = tmp_path / "base.json"
    base.write_text(ModalAutoencoderTrainingState().to_json())
    training = tmp_path / "training.jsonl"
    validation = tmp_path / "validation.jsonl"
    training.write_text(json.dumps({"title": "5", "section": "1", "text": "The officer shall retain records for at least 22 days."}) + "\n")
    validation.write_text(json.dumps({"title": "5", "section": "2", "text": "The officer shall retain records for at least 30 days."}) + "\n")
    source_hashes = {key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")}
    monkeypatch.setattr(cli, "_pin", lambda **_: source_hashes)
    monkeypatch.setattr(cli, "orchestration_hashes", lambda: {})
    return {"state_directory": str(tmp_path / "state"), "checkpoint": str(base),
            "input_jsonl": str(training), "validation_jsonl": str(validation),
            "max_seconds": 20, "source_language": "en", "model_variant": "selection-test",
            "shard_count": 1, "shard_index": 0, "workers": 2, "max_batches": 2,
            "memory_mb": 8192, "cycle_receipt": str(tmp_path / "cycle.json")}


@pytest.mark.parametrize("fresh", [None, True, False])
def test_cycle_uses_same_disjoint_tuning_rows_for_selection_and_qualification(tmp_path, monkeypatch, fresh):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qualified
    config = _selection_cycle_config(tmp_path, monkeypatch)
    if fresh is not None:
        config["fresh_training_workers"] = fresh
    calls = []
    def capture(_registry, templates, **kwargs):
        calls.append(kwargs)
        assert len(templates) == 1
        template = templates[0]
        assert [sample.text for sample in template.samples] == ["The officer shall retain records for at least 22 days."]
        assert [sample.text for sample in template.validation_samples] == ["The officer shall retain records for at least 30 days."]
        assert [sample.text for sample in template.validation_samples] == [sample["text"] for sample in kwargs["qualification_samples"]]
        assert kwargs["reuse_native_workers"] is (fresh is False)
        # This boundary stub verifies dispatch inputs only; it never claims a
        # measured optimization, qualification, or Lean admission.
        return {"dispatched_run_ids": []}
    monkeypatch.setattr(qualified, "run_qualified_incremental_training", capture)
    receipt = cli.run_cycle(config)
    assert len(calls) == 1
    assert receipt["optimizer_validation_role"] == "repeated_selection_tuning"
    assert receipt["validation_sample_count"] == 1
    assert receipt["heldout_canary"] is receipt["training_executed"] is receipt["admitted"] is False


def test_cycle_rejects_normalized_training_validation_overlap_before_dispatch(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qualified
    config = _selection_cycle_config(tmp_path, monkeypatch)
    Path(config["validation_jsonl"]).write_text(json.dumps({"title": "6", "section": "3",
        "text": "  THE officer shall retain  records for at least 22 days. "}) + "\n")
    monkeypatch.setattr(qualified.coordinator, "run_training_jobs", lambda *_args, **_kwargs: pytest.fail("overlap reached optimizer dispatch"))
    with pytest.raises(qualified.inc.IncrementalTrainingError, match="training/validation source overlap"):
        cli.run_cycle(config)
    assert not Path(config["cycle_receipt"]).exists()


@pytest.mark.parametrize("parallel,pending,memory,expected", [(0, 2, 8192, 2), (2, 4, 8192, 2), (1, 4, 8192, 1), (0, 8, 12288, 7)])
def test_supervised_cycle_reserves_proof_processes_and_avoids_immediate_duplicate_inventory(tmp_path, monkeypatch, parallel, pending, memory, expected):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    from types import SimpleNamespace
    clock, checks, finalized, admitted = [0.0], [], [], []
    monkeypatch.setattr(scheduler, "get_global_resource_scheduler", lambda: SimpleNamespace(snapshot=lambda: {}))
    monkeypatch.setattr(capacity, "scheduler_capacity", lambda _: {"cpu_slots": 8, "memory_mb": 50000, "child_process_slots": 64})
    monkeypatch.setattr(capacity, "hardware_probe", lambda: {"hardware_cpu_count": 20,
        "affinity_cpu_count": 20, "available_memory_mb": 50000})
    class Reservation:
        def __init__(self, *args, **kwargs): admitted.append(kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def check_usage(self, **kwargs): checks.append(clock[0])
        def finalize(self, **kwargs):
            assert kwargs["artifacts_durable"] is True
            finalized.append(clock[0])
            return {"status": "released"}
    class Input:
        def write(self, raw):
            config = json.loads(raw)
            assert config["reserved_cpu_slots"] == expected + 1
            assert config["reserved_child_process_slots"] == expected + 4
            assert config["max_parallel_workers"] == expected
            assert config["workers"] == 32
            Path(config["cycle_receipt"]).write_text(json.dumps({"input_count": 2,
                "training": {}, "training_executed": False, "weight_publications": []}))
        def close(self): pass
    class Process:
        pid, returncode, stdin = 12345, 0, Input()
        def __init__(self): self.calls = 0
        def poll(self):
            self.calls += 1
            return None if self.calls == 1 else 0
    monkeypatch.setattr(resources, "DaemonResourceReservation", Reservation)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(cli, "_stop_group", lambda *args: None)
    monkeypatch.setattr(cli, "_group_observation", lambda *args: {"processes": []})
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    result = cli.supervised_cycle({"execution_mode": "training", "workers": 32,
        "parallel_workers": parallel,
        "memory_mb": memory, "max_batches": pending, "state_directory": str(tmp_path / "state"),
        "resource_ledger": str(tmp_path / "ledger.json"), "resource_roots": [],
        "storage_bytes": 1000000, "cycle_timeout": 120})
    assert admitted[0]["cpu_slots"] == expected + 1 and admitted[0]["child_process_slots"] == expected + 4
    assert checks == [0.0]  # Initial check; finalization performs its own fresh census.
    assert finalized == [0.5]
    assert result["resource_finalization_seconds"] == 0.0
    assert result["capacity_plan"]["execution_envelope"]["estimated_memory_mb"] == 2048 + 1152 * expected


def test_training_nested_callback_receives_complete_reserved_cpu_envelope(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qualified
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
    config = _selection_cycle_config(tmp_path, monkeypatch)
    config.update(workers=32, max_parallel_workers=7, reserved_cpu_slots=8,
                  reserved_child_process_slots=11, memory_mb=12288, max_batches=8)
    monkeypatch.setattr(capacity, "hardware_probe", lambda: {"hardware_cpu_count": 20,
        "affinity_cpu_count": 20, "available_memory_mb": 50000})
    def capture(_registry, templates, **kwargs):
        plan = kwargs["capacity_callback"](pending_count=8, max_workers=7)
        assert plan["workers"] == 7
        assert plan["execution_envelope"]["cpu_slots"] == 8
        return {"dispatched_run_ids": []}
    monkeypatch.setattr(qualified, "run_qualified_incremental_training", capture)
    cli.run_cycle(config)


@pytest.mark.parametrize("ceiling,expected", [(0, 3), (2, 2), (1, 1)])
def test_qualification_callback_uses_existing_envelope_with_independent_ceiling(tmp_path, monkeypatch, ceiling, expected):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qualified
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
    config = _selection_cycle_config(tmp_path, monkeypatch)
    config.update(workers=32, max_parallel_workers=7, reserved_cpu_slots=8,
                  reserved_child_process_slots=11, memory_mb=12288, max_batches=8,
                  parallel_qualification_workers=ceiling)
    monkeypatch.setattr(capacity, "hardware_probe", lambda: {"hardware_cpu_count": 20,
        "affinity_cpu_count": 20, "available_memory_mb": 50000})
    def capture(_registry, templates, **kwargs):
        assert kwargs["max_qualification_workers"] == (ceiling or 32)
        result = kwargs["qualification_capacity_callback"](pending_count=8,
            max_workers=kwargs["max_qualification_workers"])
        assert result["workers"] == expected
        assert result["execution_envelope"]["cpu_slots"] <= 8
        assert result["execution_envelope"]["child_process_slots"] <= 11
        assert result["execution_envelope"]["estimated_memory_mb"] <= 12288
        return {"dispatched_run_ids": []}
    monkeypatch.setattr(qualified, "run_qualified_incremental_training", capture)
    cli.run_cycle(config)


@pytest.mark.parametrize("value", ["-1", "33"])
def test_invalid_parallel_qualification_ceiling_rejected_before_work(tmp_path, value):
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(tmp_path / "unused"), "--input-jsonl", str(tmp_path / "input"),
                  "--parallel-qualification-workers", value])
    assert not (tmp_path / "unused").exists()


def test_explicit_parallel_qualification_setting_is_training_only(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(tmp_path / "unused"), "--execution-mode", "inference",
                  "--input-jsonl", str(tmp_path / "input"), "--validation-jsonl", str(tmp_path / "validation"),
                  "--parallel-qualification-workers", "2"])
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("flag,value", [
    ("--epochs", "0"), ("--epochs", "33"), ("--line-search-attempts", "0"),
    ("--line-search-attempts", "11"), ("--learning-rate", "0"), ("--learning-rate", "1.1"),
    ("--learning-rate", "nan"), ("--learning-rate", "inf"),
    ("--projection-momentum", "-0.1"), ("--projection-momentum", "1"),
    ("--projection-momentum", "nan"), ("--projection-momentum", "inf"),
])
def test_optimizer_cli_bounds_reject_before_state_creation(tmp_path, flag, value):
    output = tmp_path / "uncreated"
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(output), "--input-jsonl", "input", flag, value])
    assert not output.exists()


@pytest.mark.parametrize("options", [
    ["--projection-optimizer-mode", "guarded_adaptive"],
    ["--projection-momentum", "0.5"],
    ["--projection-optimizer-mode", "guarded_adaptive", "--projection-momentum", "0.5", "--validation-jsonl", "validation"],
])
def test_adaptive_cli_requires_training_validation_and_momentum_budget(tmp_path, options):
    output = tmp_path / "uncreated"
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(output), "--input-jsonl", "input", *options])
    assert not output.exists()


@pytest.mark.parametrize("flag,value,key,typed", [
    ("--epochs", "2", "epochs", 2),
    ("--learning-rate", "0.2", "learning_rate", 0.2),
    ("--line-search-attempts", "2", "line_search_attempts", 2),
    ("--projection-optimizer-mode", "guarded_adaptive", "projection_optimizer_mode", "guarded_adaptive"),
])
def test_inference_rejects_nondefault_optimizer_cli_and_direct_route(tmp_path, flag, value, key, typed):
    output = tmp_path / "uncreated"
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(output), "--input-jsonl", "input", "--validation-jsonl", "validation",
                  "--execution-mode", "inference", flag, value])
    with pytest.raises(ValueError, match="training execution mode"):
        cli.run_cycle({"state_directory": str(output), "execution_mode": "inference", key: typed})
    assert not output.exists()


def test_optimizer_parser_defaults_preserve_existing_job_policy(tmp_path):
    args = cli.parser().parse_args(["--state-directory", str(tmp_path), "--input-jsonl", "input"])
    assert (args.epochs, args.learning_rate, args.line_search_attempts) == (1, 0.35, 1)
    assert args.projection_optimizer_mode == "fixed" and args.projection_momentum == 0
    assert cli._nondefault_optimizer_settings(vars(args)) is False


def test_cycle_binds_nondefault_epoch_optimizer_settings_into_job_and_policy(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qualified
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_incremental_training as incremental
    config = {**_selection_cycle_config(tmp_path, monkeypatch), "epochs": 3, "learning_rate": 0.25,
        "line_search_attempts": 2, "projection_optimizer_mode": "guarded_adaptive", "projection_momentum": 0.5}
    seen = []
    def capture(registry, templates, **kwargs):
        template = templates[0]
        options = template.to_dict()["training_config"]
        assert options["epochs"] == 3 and options["learning_rate"] == 0.25
        assert options["max_line_search_attempts"] == 2
        assert options["projection_optimizer_mode"] == "guarded_adaptive" and options["projection_momentum"] == 0.5
        assert incremental._policy(registry, template)["training_config"] == options
        assert template.validation_samples and template.samples != template.validation_samples
        seen.append(template.canonical_sha256)
        return {"dispatched_run_ids": []}
    monkeypatch.setattr(qualified, "run_qualified_incremental_training", capture)
    receipt = cli.run_cycle(config)
    assert len(seen) == 1
    assert receipt["heldout_canary"] is receipt["admitted"] is False

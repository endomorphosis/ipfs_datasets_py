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
        assert template.validation_samples == ()
        assert template.split_snapshot_id.startswith("qualification-validation-")
        no_validation = cli.make_templates(registry, [train], **opts)[0]
        assert template.split_snapshot_id != no_validation.split_snapshot_id
    args = cli.parser().parse_args(["--state-directory", str(tmp_path), "--input-jsonl", "input"])
    assert args.max_training_rounds == 3 and args.lake_timeout_seconds == 120
    assert not hasattr(args, "disable_qualification")


def test_orchestration_binds_native_grammar_and_statement_lock():
    hashes = cli.orchestration_hashes()
    assert "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py" in hashes
    assert "ipfs_datasets_py/logic/parsers/legacy_modal.py" in hashes
    assert "ipfs_datasets_py/logic/modal/decompiler.py" in hashes
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


def test_omitted_workers_follow_the_machine_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.autoformal.worker_budget.worker_budget",
        lambda **_kwargs: 5,
    )
    from ipfs_datasets_py.logic.autoformal.worker_budget import resolve_worker_count

    assert cli.parser().get_default("workers") == 0
    assert resolve_worker_count(cli.parser().get_default("workers"), maximum=32) == 5


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

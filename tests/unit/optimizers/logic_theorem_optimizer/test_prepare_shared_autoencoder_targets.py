"""Standalone producer bounds and exact existing bundle handoff.

Expensive bridge generation and ledger acquisition are explicitly injected in
unit tests. Linux process-control tests spawn only short fixture children.
"""
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py"


@pytest.fixture
def cli(monkeypatch):
    spec = importlib.util.spec_from_file_location("target_preparation_cli_fixture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helpers = module._helpers()
    monkeypatch.setattr(helpers, "_pin", lambda: {"compiler": "fixture-source"})
    return module


@pytest.fixture
def inputs(cli, tmp_path):
    train = tmp_path / "train.jsonl"
    valid = tmp_path / "valid.jsonl"
    train.write_text(json.dumps({"title": "5", "section": "fixture", "text": "The agency shall not disclose records."}) + "\n")
    valid.write_text(json.dumps({"title": "5", "section": "validation", "text": "The officer shall retain the file for at least 20 days."}) + "\n")
    args = cli.parser().parse_args([
        "--input-jsonl", str(train), "--validation-jsonl", str(valid),
        "--output-directory", str(tmp_path / "output"),
        "--resource-ledger", str(tmp_path / "resources.json"),
        "--max-output-bytes", str(1024 * 1024), "--storage-bytes", str(32 * 1024 * 1024),
    ])
    return args


def config_for(cli, inputs):
    expected = cli.plan(inputs)
    return {"plan": expected, "output_directory": str(inputs.output_directory),
            "memory_mb": inputs.memory_mb, "timeout_seconds": inputs.timeout_seconds,
            "max_output_bytes": inputs.max_output_bytes}


def test_plan_matches_existing_runner_normalization_without_output_or_reservation(cli, inputs, monkeypatch):
    monkeypatch.setattr(cli, "execute", lambda *args: pytest.fail("reserved or produced during plan"))
    plan = cli.plan(inputs)
    assert plan["training_record_count"] == plan["validation_record_count"] == 1
    assert plan["maximum_union_target_count"] == 2
    assert plan["bridge_names"] == list(cli.BRIDGES)
    assert plan["metric_disk_cache"] == 0 and plan["legal_ir_parallel_workers"] == 1
    assert plan["legal_ir_evaluate_provers"] is plan["use_sample_memory"] is False
    assert plan["admitted"] is False and not inputs.output_directory.exists()
    assert not inputs.resource_ledger.exists()
    selected = {split: [row["sample"] for row in cli._helpers().local_records(path)] for split, path in (
        ("training", inputs.input_jsonl), ("validation", inputs.validation_jsonl),
    )}
    assert plan["selection_sha256"] == hashlib.sha256(cli._canonical(selected).encode()).hexdigest()


@pytest.mark.parametrize("change,match", [
    ("overlap", "disjoint"), ("row_limit", "row bound"), ("byte_limit", "bounded regular"),
    ("empty", "nonempty"), ("symlink", "Too many levels"),
])
def test_input_failures_precede_producer_and_output_creation(cli, inputs, change, match):
    if change == "overlap":
        row = json.loads(inputs.input_jsonl.read_text());row["text"] = "  THE AGENCY  shall not disclose records. "
        inputs.validation_jsonl.write_text(json.dumps(row) + "\n")
    elif change == "row_limit":
        inputs.max_input_rows = 1
        inputs.input_jsonl.write_text(inputs.input_jsonl.read_text() * 2)
    elif change == "byte_limit":
        inputs.max_input_bytes = 10
    elif change == "empty":
        inputs.input_jsonl.write_text("\n")
    else:
        original = inputs.input_jsonl
        inputs.input_jsonl = original.with_name("alias.jsonl")
        inputs.input_jsonl.symlink_to(original)
    with pytest.raises((ValueError, OSError), match=match):
        cli.plan(inputs)
    assert not inputs.output_directory.exists()


@pytest.mark.parametrize("option,value", [
    ("--bridge-names", "deontic_norms"), ("--metric-disk-cache", "1"),
    ("--legal-ir-evaluate-provers", "true"), ("--legal-ir-parallel-workers", "2"),
    ("--timeout-seconds", "nan"), ("--memory-mb", "0"),
    ("--max-input-rows", "10001"), ("--max-output-bytes", "0"),
    ("--storage-bytes", "1"),
])
def test_invalid_cli_policy_rejected_before_intake(cli, inputs, monkeypatch, option, value):
    monkeypatch.setattr(cli, "plan", lambda *args: pytest.fail("read input before policy validation"))
    with pytest.raises(SystemExit):
        cli.main(["--input-jsonl", str(inputs.input_jsonl), "--validation-jsonl", str(inputs.validation_jsonl),
                  "--output-directory", str(inputs.output_directory), option, value])


def test_real_existing_bundle_contains_union_and_exact_hydrated_targets(cli, inputs, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as prep
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_artifact
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument

    binding = TargetSnapshotConfig(bridge_names=cli.BRIDGES, evaluate_provers=False, parallel_workers=1, code_sha256={"fixture": "0" * 64}, dependency_provenance={"target_timeout_enforcement": "fixture"})
    monkeypatch.setattr(prep, "target_snapshot_config", lambda config: binding)
    calls, originals, limits = [], {}, []
    def generate(callback, **kwargs):
        calls.append(kwargs)
        target = LegalIRTrainingTarget(cli.BRIDGES,
            LegalIRDocument(kwargs["document_id"], kwargs["text"], kwargs["text"],
                            source=kwargs["source"], citation=kwargs["citation"]),
            {"fixture_loss": 0.75}, {}, {"deontic.ir": 1.0}, False)
        originals[kwargs["document_id"]] = target
        return SimpleNamespace(training_target=lambda: target, bridge_names=cli.BRIDGES,
                               reports={}, failures={}, accepted=False)
    monkeypatch.setattr(ma, "_evaluate_legal_ir_multiview_with_timeout", generate)
    monkeypatch.setattr(cli.resource, "setrlimit", lambda kind, bounds: limits.append((kind, bounds)))
    config = config_for(cli, inputs)
    inputs.output_directory.mkdir()
    cli._produce(config)
    receipt = json.loads((inputs.output_directory / "producer.json").read_text())
    prepared = receipt["preparation"]
    assert len(calls) == prepared["legal_ir_target_count"] == prepared["sample_count"] == 2
    assert all(call["bridge_names"] == cli.BRIDGES and call["evaluate_provers"] is False and call["cache"] is False for call in calls)
    assert limits == [(cli.resource.RLIMIT_FSIZE, (inputs.max_output_bytes, inputs.max_output_bytes))]
    assert prepared["artifact_format"] == "bundle" and prepared["admitted"] is False
    assert set(prepared["statuses"].values()) == {"ready"}
    assert all(row["report_accepted"] is False for row in prepared["bridge_report_telemetry"].values())
    records = [SampleRecord.from_dict(row["sample"]) for path in (inputs.input_jsonl, inputs.validation_jsonl)
               for row in cli._helpers().local_records(path)]
    samples = [build_us_code_sample(**asdict(row)) for row in records]
    with load_target_artifact(prepared["artifact"]["path"], expected_sha256=prepared["artifact"]["sha256"], config=binding) as snapshot:
        actual = snapshot.targets_for(samples, config=binding)
        assert actual == originals
        assert snapshot.snapshot_id == prepared["target_snapshot_id"]


def test_mutated_input_refused_before_target_generation(cli, inputs, monkeypatch):
    config = config_for(cli, inputs)
    inputs.input_jsonl.write_text(inputs.input_jsonl.read_text().replace("records", "files"))
    monkeypatch.setattr(cli.resource, "setrlimit", lambda *a: pytest.fail("producer reached after changed input"))
    with pytest.raises(ValueError, match="input changed"):
        cli._produce(config)


class ReservationFixture:
    """Only process ownership/order is tested here; not host resource admission."""
    def __init__(self):
        self.calls = []
    def check_usage(self, **kwargs):
        self.calls.append(kwargs)
        if "child_pid" in kwargs:
            assert not (kwargs["attempt_directory"] / "started.json").exists()


def child_config(tmp_path, timeout=3):
    return {"output_directory": str(tmp_path), "memory_mb": 128, "timeout_seconds": timeout}


def test_linux_child_cannot_start_work_before_owned_usage_attachment(cli, tmp_path):
    reservation = ReservationFixture()
    code = "import sys,json,pathlib; cfg=json.loads(sys.stdin.readline()); pathlib.Path(cfg['output_directory'],'started.json').write_text('true')"
    result = cli._supervise(child_config(tmp_path), reservation, child_argv=[sys.executable, "-c", code])
    assert json.loads((tmp_path / "started.json").read_text()) is True
    assert reservation.calls[0]["child_pid"] > 0
    assert len(reservation.calls) == 1  # Final census belongs to execute.finalize.
    assert result["supervised_process_wall_seconds"] > 0


def test_linux_child_deadline_stops_and_reaps_owned_process(cli, tmp_path):
    code = "import sys,json,pathlib,os,time; cfg=json.loads(sys.stdin.readline()); pathlib.Path(cfg['output_directory'],'pid').write_text(str(os.getpid())); time.sleep(60)"
    with pytest.raises(TimeoutError):
        cli._supervise(child_config(tmp_path, timeout=.2), ReservationFixture(), child_argv=[sys.executable, "-c", code])
    pid = int((tmp_path / "pid").read_text())
    assert not Path(f"/proc/{pid}").exists()


def test_linux_child_failure_is_retained_and_not_handoff(cli, tmp_path):
    with pytest.raises(RuntimeError, match="producer failed"):
        cli._supervise(child_config(tmp_path), ReservationFixture(),
                       child_argv=[sys.executable, "-c", "import sys;sys.stdin.readline();print('fixture failure');sys.exit(7)"])
    assert "fixture failure" in (tmp_path / "producer.log").read_text()
    assert not (tmp_path / "receipt.json").exists()


def test_sigterm_stops_child_before_propagating_interruption(cli, tmp_path):
    code = "import sys,json,pathlib,os,time; cfg=json.loads(sys.stdin.readline()); pathlib.Path(cfg['output_directory'],'pid').write_text(str(os.getpid())); time.sleep(60)"
    def interrupt():
        deadline = time.monotonic() + 5
        while not (tmp_path / "pid").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        if (tmp_path / "pid").exists():
            os.kill(os.getpid(), signal.SIGTERM)
    thread = threading.Thread(target=interrupt)
    thread.start()
    try:
        with pytest.raises(InterruptedError):
            cli._supervise(child_config(tmp_path), ReservationFixture(), child_argv=[sys.executable, "-c", code])
    finally:
        thread.join(timeout=6)
    pid = int((tmp_path / "pid").read_text())
    assert not Path(f"/proc/{pid}").exists()


class LedgerFixture(ReservationFixture):
    """An injected lifecycle boundary, never a claim of native admission."""
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.status = "created"
        self.configuration = kwargs
    def __enter__(self):
        self.status = "reserved"
        return self
    def __exit__(self, *args):
        if self.status != "released":
            self.status = "retained"
    def finalize(self, attempt_directory, *, artifacts_durable):
        assert artifacts_durable is True
        assert (attempt_directory / "targets.bundle").is_file()
        assert (attempt_directory / "producer.json").is_file()
        self.finalized_directory = attempt_directory
        self.status = "released"
        return self.to_dict()
    def to_dict(self):
        return {"status": self.status}


@pytest.mark.parametrize("fault", [None, "oversized", "changed_input", "child_failure", "finalization_failure"])
def test_handoff_requires_intact_artifact_and_preserves_failed_reservation(cli, inputs, monkeypatch, fault):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    leases = []
    def reserve(*args, **kwargs):
        lease = LedgerFixture(*args, **kwargs)
        if fault == "finalization_failure":
            def fail_finalization(**kwargs):
                raise ValueError("fixture final accounting limit exceeded")
            lease.finalize = fail_finalization
        leases.append(lease)
        return lease
    monkeypatch.setattr(resources, "DaemonResourceReservation", reserve)
    def producer_boundary(config, reservation):
        if fault == "child_failure":
            raise RuntimeError("fixture producer failed")
        directory = Path(config["output_directory"])
        (directory / "targets.bundle").write_bytes(b'x' * (inputs.max_output_bytes + 1) if fault == "oversized" else b"fixture-target")
        if fault == "changed_input":
            inputs.input_jsonl.write_text(inputs.input_jsonl.read_text().replace("records", "files"))
        preparation = {"artifact": cli._descriptor(directory / "targets.bundle"),
                       "target_snapshot_id": "fixture-snapshot", "sample_count": 2, "legal_ir_target_count": 2}
        cli._helpers()._write(directory / "producer.json", {"plan": config["plan"], "preparation": preparation})
        return {"fixture_supervision": True}
    monkeypatch.setattr(cli, "_supervise", producer_boundary)
    expected = cli.plan(inputs)
    if fault:
        with pytest.raises((RuntimeError, ValueError)):
            cli.execute(inputs, expected)
        assert leases[0].status == "retained"
        assert (inputs.output_directory / "failure.json").exists()
        assert not (inputs.output_directory / "receipt.json").exists()
    else:
        result = cli.execute(inputs, expected)
        assert leases[0].status == "released"
        assert leases[0].finalized_directory == inputs.output_directory
        assert result["runner_arguments"] == ["--shared-targets", str(inputs.output_directory / "targets.bundle"),
                                               "--target-snapshot-id", "fixture-snapshot"]
        assert result["training_job_fields"] == {
            "target_snapshot_id": "fixture-snapshot",
            "target_snapshot_artifact": result["target_artifact"],
        }
        assert result["legal_ir_target_count"] == 2
        assert result["training_executed"] is result["model_weights_downloaded"] is result["admitted"] is False
        assert result["preparation_including_input_planning_seconds"] >= result["target_preparation_wall_seconds"]
        assert json.loads((inputs.output_directory / "resources.json").read_text())["status"] == "released"
    assert leases[0].configuration["cpu_slots"] == 1
    assert leases[0].configuration["child_process_slots"] == 3
    assert leases[0].configuration["storage_bytes"] == inputs.storage_bytes


def test_existing_output_is_rejected_before_intake(cli, inputs, monkeypatch):
    inputs.output_directory.mkdir()
    sentinel = inputs.output_directory / "keep"
    sentinel.write_text("retained")
    monkeypatch.setattr(cli, "plan", lambda *a: pytest.fail("intake before output collision rejected"))
    with pytest.raises(SystemExit):
        cli.main(["--input-jsonl", str(inputs.input_jsonl), "--validation-jsonl", str(inputs.validation_jsonl),
                  "--output-directory", str(inputs.output_directory)])
    assert sentinel.read_text() == "retained"

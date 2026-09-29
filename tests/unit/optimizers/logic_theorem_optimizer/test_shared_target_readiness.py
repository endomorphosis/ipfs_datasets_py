"""Bounded target-budget handoff and fail-closed completeness; no live bridges."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as prep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import BRIDGE_NAMES


def observation(*, accepted=True):
    return {"report_received": True, "report_accepted": accepted, "failures": {}, "outer_timeout": None,
        **{kind + "_bridge_names": list(BRIDGE_NAMES) if kind != "failed" else []
           for kind in ("attempted", "implemented", "accepted", "failed")},
        **{kind + "_bridge_count": len(BRIDGE_NAMES) if kind != "failed" else 0
           for kind in ("attempted", "implemented", "accepted", "failed")}}


def test_completeness_does_not_grant_proof_authority():
    result = prep.target_supervision_completeness({"train": "ready"}, {"train": observation()}, BRIDGE_NAMES)
    assert result["complete"] is True and result["complete_target_count"] == 1
    assert result["admitted"] is False and "not a Lean admission" in result["scope"]


@pytest.mark.parametrize("failure", ["timeout", "partial", "rejected", "missing_bridge", "exception"])
def test_incomplete_supervision_remains_explicit(failure):
    statuses, row = {"train": "ready"}, observation()
    if failure == "timeout":
        statuses["train"] = "timeout"
        row = prep._bridge_report_telemetry(outer_timeout=modal._LegalIRTargetTimeout("fixture"))
    elif failure == "partial":
        row["accepted_bridge_names"] = list(BRIDGE_NAMES[:-1]); row["accepted_bridge_count"] -= 1
        row["report_accepted"] = False
    elif failure == "rejected":
        row["report_accepted"] = False
    elif failure == "missing_bridge":
        row["implemented_bridge_names"] = list(BRIDGE_NAMES[:-1]); row["implemented_bridge_count"] -= 1
    else:
        row["failures"] = {BRIDGE_NAMES[-1]: "fixture exception"}
        row["failed_bridge_names"] = [BRIDGE_NAMES[-1]]; row["failed_bridge_count"] = 1
    before = deepcopy(row)
    result = prep.target_supervision_completeness(statuses, {"train": row}, BRIDGE_NAMES)
    assert result["complete"] is False and result["incomplete_target_count"] == 1
    assert result["observations"]["train"]["reasons"]
    assert row == before and result["admitted"] is False


@pytest.mark.parametrize("fault", ["empty", "unknown_status", "missing_observation", "nonbool_acceptance",
                                   "bad_count", "duplicate_bridge", "false_missing_report_acceptance",
                                   "missing_field", "unknown_returned_acceptance", "malformed_failure"])
def test_malformed_observations_fail_explicitly(fault):
    statuses, telemetry = {"row": "ready"}, {"row": observation()}
    if fault == "empty": statuses, telemetry = {}, {}
    elif fault == "unknown_status": statuses["row"] = "roundtrip_ok"
    elif fault == "missing_observation": telemetry = {}
    elif fault == "nonbool_acceptance": telemetry["row"]["report_accepted"] = 1
    elif fault == "bad_count": telemetry["row"]["accepted_bridge_count"] = 0
    elif fault == "duplicate_bridge": telemetry["row"]["implemented_bridge_names"][1] = BRIDGE_NAMES[0]
    elif fault == "missing_field": del telemetry["row"]["report_accepted"]
    elif fault == "unknown_returned_acceptance": telemetry["row"]["report_accepted"] = None
    elif fault == "malformed_failure": telemetry["row"]["failures"] = {"bridge": 1}
    else:
        telemetry["row"] = prep._bridge_report_telemetry()
        telemetry["row"]["report_accepted"] = False
    with pytest.raises(ValueError):
        prep.target_supervision_completeness(statuses, telemetry, BRIDGE_NAMES)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[4]
    path = root / "scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py"
    spec = importlib.util.spec_from_file_location("target_readiness_cli", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module._helpers(), "_pin", lambda: {"fixture": "0" * 64})
    train, tune = tmp_path / "train.jsonl", tmp_path / "tune.jsonl"
    train.write_text(json.dumps({"title": "5", "section": "1", "text": "The agency shall retain records."}) + "\n")
    tune.write_text(json.dumps({"title": "5", "section": "2", "text": "The officer shall publish notices."}) + "\n")
    args = module.parser().parse_args(["--input-jsonl", str(train), "--validation-jsonl", str(tune),
                                      "--output-directory", str(tmp_path / "output")])
    return module, args


@pytest.mark.parametrize("explicit,environment,expected", [(None, None, 15.), (None, "31", 31.), (60., "31", 60.)])
def test_plan_binds_effective_timeout_and_consumer_environment(cli, monkeypatch, explicit, environment, expected):
    module, args = cli
    monkeypatch.delenv(module.TARGET_TIMEOUT_ENV, raising=False)
    if environment is not None: monkeypatch.setenv(module.TARGET_TIMEOUT_ENV, environment)
    args.target_timeout_seconds = explicit
    result = module.plan(args)
    assert result["target_timeout_seconds"] == expected
    assert result["runner_environment"] == {module.TARGET_TIMEOUT_ENV: str(expected)}
    assert result["require_complete_targets"] is False
    with module._target_timeout_environment(expected):
        assert modal._legal_ir_target_timeout_seconds() == expected
    import os
    assert os.environ.get(module.TARGET_TIMEOUT_ENV) == environment


@pytest.mark.parametrize("value", ["0", "-1", "601", "nan", "inf"])
def test_invalid_explicit_timeout_refused_before_intake(cli, monkeypatch, value):
    module, args = cli
    monkeypatch.setattr(module, "plan", lambda *args: pytest.fail("intake preceded timeout validation"))
    with pytest.raises(SystemExit):
        module.main(["--input-jsonl", str(args.input_jsonl), "--validation-jsonl", str(args.validation_jsonl),
                     "--output-directory", str(args.output_directory), "--target-timeout-seconds", value])


def test_strict_handoff_rejects_incomplete_and_forged_summary(cli):
    module, args = cli
    expected = module.plan(args)
    expected["require_complete_targets"] = True
    statuses = {"row": "timeout"}
    telemetry = {"row": prep._bridge_report_telemetry(outer_timeout=modal._LegalIRTargetTimeout("fixture"))}
    result = {"statuses": statuses, "bridge_report_telemetry": telemetry,
              "target_timeout_seconds": expected["target_timeout_seconds"],
              "target_shard_max_bytes": expected["target_shard_max_bytes"],
              "target_completeness": prep.target_supervision_completeness(statuses, telemetry, BRIDGE_NAMES)}
    with pytest.raises(ValueError, match="complete target supervision required"):
        module._verify_target_completeness(result, expected)
    result["target_completeness"]["complete"] = True
    with pytest.raises(ValueError, match="differs from producer observations"):
        module._verify_target_completeness(result, expected)


def test_strict_producer_retains_timeout_artifact_and_observations(cli, monkeypatch):
    module, args = cli
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    binding = TargetSnapshotConfig(BRIDGE_NAMES, False, 1, {"fixture": "0" * 64},
                                    {"target_timeout_enforcement": "fixture"})
    monkeypatch.setattr(prep, "target_snapshot_config", lambda _: binding)
    monkeypatch.setattr(module.resource, "setrlimit", lambda *args: None)
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout",
                        lambda *args, **kwargs: (_ for _ in ()).throw(modal._LegalIRTargetTimeout("fixture")))
    args.require_complete_targets = True
    args.output_directory.mkdir()
    expected = module.plan(args)
    config = {"plan": expected, "output_directory": str(args.output_directory),
              "max_output_bytes": args.max_output_bytes}
    with pytest.raises(ValueError, match="complete target supervision required"):
        module._produce(config)
    assert (args.output_directory / "targets.bundle").exists()
    producer = json.loads((args.output_directory / "producer.json").read_text())
    assert producer["preparation"]["target_completeness"]["complete"] is False
    assert set(producer["preparation"]["statuses"].values()) == {"timeout"}
    journal = [json.loads(line) for line in (args.output_directory / "target-observations.jsonl").read_text().splitlines()]
    assert len(journal) == 2 and {row["status"] for row in journal} == {"timeout"}
    assert all(row["admitted"] is False and row["bridge_report_telemetry"]["outer_timeout"] for row in journal)
    assert not (args.output_directory / "receipt.json").exists()


def test_explicit_timeout_applies_only_during_child_generation(cli, monkeypatch):
    module, args = cli
    from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle
    monkeypatch.setenv(module.TARGET_TIMEOUT_ENV, "31")
    args.target_timeout_seconds = 60.
    args.target_shard_max_bytes = 256 * 1024 * 1024
    writer_bounds = []
    original_writer = bundle.write_target_bundle
    def bounded_writer(*args, **kwargs):
        writer_bounds.append(kwargs["max_shard_bytes"])
        return original_writer(*args, **kwargs)
    monkeypatch.setattr(bundle, "write_target_bundle", bounded_writer)
    binding = TargetSnapshotConfig(BRIDGE_NAMES, False, 1, {"fixture": "0" * 64},
                                    {"target_timeout_enforcement": "fixture"}, target_timeout_seconds=60.)
    monkeypatch.setattr(prep, "target_snapshot_config", lambda _: binding)
    monkeypatch.setattr(module.resource, "setrlimit", lambda *args: None)
    calls = []
    def generate(callback, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        assert modal._legal_ir_target_timeout_seconds() == 60.
        target = LegalIRTrainingTarget(BRIDGE_NAMES,
            LegalIRDocument(kwargs["document_id"], kwargs["text"], kwargs["text"], source=kwargs["source"]),
            {}, {}, {}, True)
        return SimpleNamespace(training_target=lambda: target, bridge_names=BRIDGE_NAMES,
                               reports={name: SimpleNamespace(accepted=True) for name in BRIDGE_NAMES},
                               failures={}, accepted=True)
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    args.require_complete_targets = True
    args.output_directory.mkdir()
    expected = module.plan(args)
    module._produce({"plan": expected, "output_directory": str(args.output_directory),
                     "max_output_bytes": args.max_output_bytes})
    assert calls == [60., 60.] and modal._legal_ir_target_timeout_seconds() == 31.
    result = json.loads((args.output_directory / "producer.json").read_text())["preparation"]
    assert result["target_timeout_seconds"] == 60.
    assert result["target_shard_max_bytes"] == 256 * 1024 * 1024
    assert writer_bounds == [256 * 1024 * 1024]
    assert result["target_completeness"]["complete"] is True


@pytest.mark.parametrize("bound", [0, -1, 256 * 1024 * 1024 + 1, True, 1.5])
def test_preparer_rejects_invalid_expanded_bound_before_generation(tmp_path, monkeypatch, bound):
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout",
                        lambda *args, **kwargs: pytest.fail("native generation must not start"))
    with pytest.raises(ValueError, match="target_shard_max_bytes"):
        prep.prepare_training_targets([], tmp_path / "never.bundle", artifact_format="bundle",
                                      target_shard_max_bytes=bound)
    assert not (tmp_path / "never.bundle").exists()


@pytest.mark.parametrize("bound", ["0", "-1", str(256 * 1024 * 1024 + 1)])
def test_cli_rejects_invalid_expanded_bound_before_intake(cli, monkeypatch, bound):
    module, args = cli
    monkeypatch.setattr(module, "_selection", lambda *_: pytest.fail("input intake must not start"))
    with pytest.raises(SystemExit):
        module.main(["--input-jsonl", str(args.input_jsonl), "--validation-jsonl", str(args.validation_jsonl),
                     "--output-directory", str(args.output_directory), "--target-shard-max-bytes", bound])


def test_shard_bound_is_separate_from_compressed_output_bound(cli):
    module, args = cli
    assert args.target_shard_max_bytes == 64 * 1024 * 1024
    args.target_shard_max_bytes = 256 * 1024 * 1024
    args.max_output_bytes = 64 * 1024 * 1024
    result = module.plan(args)
    assert result["target_shard_max_bytes"] == 256 * 1024 * 1024
    assert result["max_output_bytes"] == 64 * 1024 * 1024


def test_handoff_rejects_unbound_expanded_target_allowance(cli):
    module, args = cli
    expected = module.plan(args)
    statuses, telemetry = {"row": "ready"}, {"row": observation()}
    result = {"statuses": statuses, "bridge_report_telemetry": telemetry,
              "target_timeout_seconds": expected["target_timeout_seconds"],
              "target_shard_max_bytes": 256 * 1024 * 1024,
              "target_completeness": prep.target_supervision_completeness(statuses, telemetry, BRIDGE_NAMES)}
    with pytest.raises(ValueError, match="expanded shard bound differs"):
        module._verify_target_completeness(result, expected)


def _journal_row(sample_id="row"):
    return {"sample_id": sample_id, "status": "ready", "target_generation_seconds": 1.25,
            "bridge_report_telemetry": observation(), "admitted": False}


def test_journal_flushes_each_bounded_observation_and_preserves_prefix(cli, tmp_path, monkeypatch):
    module, _ = cli
    calls, original_fsync = [], module.os.fsync
    def fsync(fd):
        calls.append(fd)
        original_fsync(fd)
    monkeypatch.setattr(module.os, "fsync", fsync)
    path = tmp_path / "journal.jsonl"
    with module._ObservationJournal(path, max_records=1, max_bytes=4096) as journal:
        journal.append(_journal_row())
        assert json.loads(path.read_text()) == _journal_row()
        assert len(calls) == 3  # file creation, parent directory, first record
        with pytest.raises(ValueError, match="bound exceeded"):
            journal.append(_journal_row("second"))
    assert json.loads(path.read_text()) == _journal_row()
    with pytest.raises(FileExistsError):
        with module._ObservationJournal(path, max_records=1, max_bytes=4096):
            pass


@pytest.mark.parametrize("fault", ["bytes", "duplicate", "admit", "text", "nonfinite"])
def test_journal_rejects_oversize_or_invalid_metadata_without_truncation(cli, tmp_path, fault):
    module, _ = cli
    path = tmp_path / "journal.jsonl"
    with module._ObservationJournal(path, max_records=2, max_bytes=4096) as journal:
        journal.append(_journal_row())
        prior = path.read_bytes()
        row = _journal_row("second")
        if fault == "bytes":
            row["bridge_report_telemetry"]["failures"] = {"bridge": "x" * 4096}
        elif fault == "duplicate": row["sample_id"] = "row"
        elif fault == "admit": row["admitted"] = True
        elif fault == "text": row["source_text"] = "must not be journaled"
        else: row["target_generation_seconds"] = float("nan")
        with pytest.raises(ValueError):
            journal.append(row)
        assert path.read_bytes() == prior


def test_writer_failure_retains_first_native_observation_without_handoff(cli, monkeypatch):
    module, args = cli
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle
    binding = TargetSnapshotConfig(BRIDGE_NAMES, False, 1, {"fixture": "0" * 64},
                                    {"target_timeout_enforcement": "fixture"})
    monkeypatch.setattr(prep, "target_snapshot_config", lambda _: binding)
    monkeypatch.setattr(module.resource, "setrlimit", lambda *args: None)
    calls = []
    def generate(callback, **kwargs):
        calls.append(kwargs["document_id"])
        return SimpleNamespace(training_target=lambda: object(), bridge_names=BRIDGE_NAMES,
                               reports={name: SimpleNamespace(accepted=True) for name in BRIDGE_NAMES},
                               failures={}, accepted=True)
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    def failing_writer(path, records, **kwargs):
        next(records)
        raise ValueError("fixture serialization bound failure")
    monkeypatch.setattr(bundle, "write_target_bundle", failing_writer)
    args.output_directory.mkdir()
    expected = module.plan(args)
    with pytest.raises(ValueError, match="serialization bound failure"):
        module._produce({"plan": expected, "output_directory": str(args.output_directory),
                         "max_output_bytes": args.max_output_bytes})
    rows = [json.loads(line) for line in (args.output_directory / "target-observations.jsonl").read_text().splitlines()]
    assert len(rows) == len(calls) == 1
    assert rows[0]["sample_id"] == calls[0] and rows[0]["status"] == "ready"
    expected_telemetry = observation()
    for key in ("implemented_bridge_names", "accepted_bridge_names"):
        expected_telemetry[key] = sorted(expected_telemetry[key])
    assert rows[0]["bridge_report_telemetry"] == expected_telemetry
    assert rows[0]["target_generation_seconds"] >= 0 and rows[0]["admitted"] is False
    assert not any((args.output_directory / name).exists() for name in ("targets.bundle", "producer.json", "receipt.json"))

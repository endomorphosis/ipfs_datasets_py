"""Pure checker adversarial fixtures; these never run or qualify native work."""
from copy import deepcopy
import hashlib
import xml.etree.ElementTree as ET

import pytest

from ipfs_datasets_py.logic.autoformal import span_claim_acceptance as subject


def fixture():
    pins = [dict(path=name, bytes=1, sha256="a" * 64) for name in subject.SOURCE_FILES]
    manifest = dict(schema=subject.MANIFEST_SCHEMA, criterion_key=subject.CRITERION,
        task_cid="fixture-task", validation_key="fixture-validator", repository_commit="b" * 40,
        declared_native_tree_id="fixture-untrusted-tree", source_pins=pins,
        test_modules=list(subject.TEST_MODULES), expected_cases=list(subject.EXPECTED_CASES),
        scenarios=subject.scenario_manifest())
    suite = ET.Element("testsuite", tests=str(len(subject.EXPECTED_CASES)), failures="0", errors="0", skipped="0")
    for case in subject.EXPECTED_CASES:
        module, name = case.split("::", 1)
        ET.SubElement(suite, "testcase", classname=module[:-3].replace("/", "."), name=name)
    junit = ET.tostring(suite)
    events = dict(run_id="fixture-run", phases=[dict(nodeid=case, when=when, outcome="passed")
        for case in subject.EXPECTED_CASES for when in ("setup", "call", "teardown")],
        origins=[pin for pin in pins if pin["path"].startswith("ipfs_datasets_py/")],
        duckdb_version="1.5.5", transport_schema="ipfs_datasets_py/autoencoder-quack-prototype@1",
        native_storage_opt_in="1")
    lease = dict(lease_id="fixture-lease", policy_sha256="c" * 64, lane="validation",
        owner_pid=42, request_id="fixture-request", cpu_slots=1, memory_mb=1536, child_process_slots=2)
    invocation = dict(run_id="fixture-run", repository_root="/fixture-untrusted", repository_commit="b" * 40,
        manifest_sha256=subject.digest(manifest), argv=["fixture-no-execution"], lease_id="fixture-lease", policy_sha256="c" * 64,
        resource_request_id="fixture-request")
    event_bytes = subject.raw(events)
    report = dict(schema=subject.SCHEMA, manifest_sha256=subject.digest(manifest), invocation=deepcopy(invocation),
        pins_before=deepcopy(pins), pins_after=deepcopy(pins), returncode=0,
        junit=dict(bytes=len(junit), sha256=hashlib.sha256(junit).hexdigest()),
        events=dict(bytes=len(event_bytes), sha256=hashlib.sha256(event_bytes).hexdigest()),
        lease_before=deepcopy(lease), lease_after=deepcopy(lease), elapsed_seconds=1.0,
        cleanup_complete=True, **subject.FALSE)
    return manifest, report, junit, events, invocation


def verify(manifest, report, junit, events, invocation):
    encoded = subject.raw(events)
    report["events"] = dict(bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest())
    return subject.verify_report(manifest, report, junit, encoded, expected_invocation=invocation)


def test_pure_complete_fixture_can_only_establish_mechanical_consistency():
    checked = verify(*fixture())
    assert checked["actual_test_count"] == 121 and checked["actual_test_skips"] == 0
    assert checked["engineering_gate_passed"] is True
    assert all(checked[name] is False for name in subject.FALSE)
    assert "independent native owner material" in checked["scope"]


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra", "failed", "error", "skipped", "missing_identity", "doctype"])
def test_junit_rejects_missing_duplicate_skipped_and_forged_single_pass(kind):
    manifest, report, junit, events, invocation = fixture()
    root = ET.fromstring(junit)
    if kind == "missing":
        root.remove(root[-1])
    elif kind == "duplicate":
        root.append(deepcopy(root[0]))
    elif kind == "extra":
        ET.SubElement(root, "testcase", classname="untrusted", name="test_forged")
    elif kind in ("failed", "error", "skipped"):
        ET.SubElement(root[0], "failure" if kind == "failed" else kind)
    elif kind == "missing_identity":
        root[0].attrib.pop("classname")
    changed = ET.tostring(root)
    if kind == "doctype":
        changed = b'<!DOCTYPE testsuite>' + changed
    report["junit"] = dict(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verify(manifest, report, changed, events, invocation)


def test_standalone_forged_junit_pass_boolean_has_no_native_phase_coverage():
    manifest, report, junit, events, invocation = fixture()
    events["phases"] = [{"nodeid": subject.EXPECTED_CASES[0], "when": "call", "outcome": "passed"}]
    with pytest.raises(subject.SpanClaimAcceptanceError, match="phase stream"):
        verify(manifest, report, junit, events, invocation)


@pytest.mark.parametrize("kind", ["duplicate", "missing", "skip", "wrong_case", "wrong_phase", "wrong_run", "wrong_opt_in", "wrong_engine", "wrong_transport"])
def test_independent_phase_stream_and_native_identity_are_required(kind):
    manifest, report, junit, events, invocation = fixture()
    if kind == "duplicate":
        events["phases"][-1] = deepcopy(events["phases"][0])
    elif kind == "missing":
        events["phases"].pop()
    elif kind == "skip":
        events["phases"][0]["outcome"] = "skipped"
    elif kind == "wrong_case":
        events["phases"][0]["nodeid"] = "test_fake"
    elif kind == "wrong_phase":
        events["phases"][0]["when"] = "invented"
    elif kind == "wrong_run":
        events["run_id"] = "other-run"
    elif kind == "wrong_opt_in":
        events["native_storage_opt_in"] = "0"
    elif kind == "wrong_engine":
        events["duckdb_version"] = "wrong"
    else:
        events["transport_schema"] = "wrong"
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verify(manifest, report, junit, events, invocation)


@pytest.mark.parametrize("kind", ["origin_hash", "origin_missing", "origin_duplicate", "origin_foreign", "pin_before", "pin_after", "junit_hash", "event_hash"])
def test_forged_source_or_evidence_references_refuse(kind):
    manifest, report, junit, events, invocation = fixture()
    if kind == "origin_hash":
        events["origins"][0]["sha256"] = "d" * 64
    elif kind == "origin_missing":
        events["origins"] = []
    elif kind == "origin_duplicate":
        events["origins"].append(deepcopy(events["origins"][0]))
    elif kind == "origin_foreign":
        events["origins"][0]["path"] = "/HACC/foreign.py"
    elif kind.startswith("pin_"):
        report["pins_" + kind.split("_")[1]][0]["sha256"] = "d" * 64
    elif kind == "junit_hash":
        report["junit"]["sha256"] = "d" * 64
    else:
        encoded = subject.raw(events)
        report["events"]["sha256"] = "d" * 64
        with pytest.raises(subject.SpanClaimAcceptanceError, match="forged evidence"):
            subject.verify_report(manifest, report, junit, encoded, expected_invocation=invocation)
        return
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verify(manifest, report, junit, events, invocation)


@pytest.mark.parametrize("kind", ["criterion", "cases", "scenarios", "modules", "task", "native_tree", "source_pin"])
def test_manifest_cannot_be_repaired_into_another_invocation(kind):
    manifest, report, junit, events, invocation = fixture()
    if kind == "criterion":
        manifest["criterion_key"] = "other"
    elif kind == "cases":
        manifest["expected_cases"].pop()
    elif kind == "scenarios":
        manifest["scenarios"].pop()
    elif kind == "modules":
        manifest["test_modules"] = ["malicious.py"]
    elif kind == "task":
        manifest["task_cid"] = "changed-task"
    elif kind == "native_tree":
        manifest["declared_native_tree_id"] = "changed-tree"
    else:
        manifest["source_pins"][0]["sha256"] = "d" * 64
        report["pins_before"] = deepcopy(manifest["source_pins"])
        report["pins_after"] = deepcopy(manifest["source_pins"])
    report["manifest_sha256"] = subject.digest(manifest)
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verify(manifest, report, junit, events, invocation)


@pytest.mark.parametrize("field", list(subject.FALSE))
def test_engineering_checker_cannot_promote_authority_flags(field):
    manifest, report, junit, events, invocation = fixture()
    report[field] = True
    with pytest.raises(subject.SpanClaimAcceptanceError, match="authority promotion"):
        verify(manifest, report, junit, events, invocation)


@pytest.mark.parametrize("kind", ["exit", "cleanup", "invocation", "lease_id", "lease_policy", "lease_request", "lease_lane", "lease_cpu", "lease_memory", "lease_children"])
def test_native_run_or_reservation_failure_refuses(kind):
    manifest, report, junit, events, invocation = fixture()
    if kind == "exit":
        report["returncode"] = 1
    elif kind == "cleanup":
        report["cleanup_complete"] = False
    elif kind == "invocation":
        report["invocation"]["run_id"] = "changed"
    else:
        field, value = {
            "lease_id": ("lease_id", "changed"), "lease_policy": ("policy_sha256", "d" * 64),
            "lease_request": ("request_id", "changed"), "lease_lane": ("lane", "trainer"),
            "lease_cpu": ("cpu_slots", 0), "lease_memory": ("memory_mb", 0),
            "lease_children": ("child_process_slots", 1),
        }[kind]
        report["lease_after"][field] = value
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verify(manifest, report, junit, events, invocation)


def test_duplicate_manifest_json_keys_are_rejected():
    with pytest.raises(subject.SpanClaimAcceptanceError):
        subject.load_json(b'{"schema":"first","schema":"second"}')


def test_live_runner_has_no_unverified_lease_default(tmp_path):
    manifest, _, _, _, _ = fixture()
    with pytest.raises(subject.SpanClaimAcceptanceError, match="explicit native lease verifier"):
        subject.run_private_checks(tmp_path, manifest, tmp_path / "output", lease_verifier=None)
    assert not (tmp_path / "output").exists()


def test_fixed_live_profile_retains_native_cacheprovider_only_in_fresh_runtime(tmp_path):
    runtime = tmp_path / "fresh-private-runtime"
    command = subject._command(runtime, tmp_path / "observed.junit.xml")
    assert "no:cacheprovider" not in command
    assert "cache_dir=" + str(runtime / "cache") in command
    assert "addopts=" in command and "--run-network" in command
    assert command[-2:] == list(subject.TEST_MODULES)
    assert command[command.index("--basetemp") + 1] == str(runtime / "pytest")


def test_missing_child_evidence_retains_bounded_failure_without_synthetic_phases(tmp_path):
    manifest, report, _, _, invocation = fixture()
    failure = subject._failure_record(tmp_path, manifest, invocation,
        report["pins_before"], report["pins_after"], report["lease_before"], report["lease_after"],
        3, 0.25, True, "FileNotFoundError")
    assert failure["returncode"] == 3
    assert failure["evidence"] == {"native-tests.junit.xml": None, "native-events.json": None}
    assert failure["synthetic_junit_or_phases_created"] is False
    assert failure["invocation"] == invocation
    assert all(failure[name] is False for name in subject.FALSE)
    assert not (tmp_path / "native-tests.junit.xml").exists()
    assert not (tmp_path / "native-events.json").exists()


def test_failure_keeps_only_actual_child_evidence_hashes(tmp_path):
    manifest, report, junit, _, invocation = fixture()
    (tmp_path / "native-tests.junit.xml").write_bytes(junit)
    failure = subject._failure_record(tmp_path, manifest, invocation,
        report["pins_before"], None, report["lease_before"], None, 1, 0.1, True, "RuntimeError")
    assert failure["pins_after"] is None and failure["lease_after"] is None
    assert failure["evidence"]["native-tests.junit.xml"] == report["junit"]
    assert failure["evidence"]["native-events.json"] is None


def _cli_module(name):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/check_span_claim_acceptance.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_sigterm_unwinds_owned_child_and_runtime_then_restores_handler(tmp_path, monkeypatch, capsys):
    """Control-flow fixture only: no native lease, storage, child or test run."""
    import json
    import signal
    module = _cli_module("t02_acceptance_cli_cancellation_test")
    manifest, report, _, _, _ = fixture()
    manifest_path, output = tmp_path / "manifest.json", tmp_path / "output"
    manifest_path.write_bytes(subject.raw(manifest))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(subject, "_head", lambda root: manifest["repository_commit"])
    monkeypatch.setattr(subject, "source_pins", lambda root: manifest["source_pins"])
    monkeypatch.setattr(subject, "_command", lambda runtime, junit: ["unit-control-flow-child"])
    monkeypatch.setenv(module.STATE_ENV, "unit-control-flow-state")
    monkeypatch.setenv(module.POLICY_ENV, report["lease_before"]["policy_sha256"])

    class UnitLeaseVerifier:
        def __init__(self, state, policy):
            assert state == "unit-control-flow-state"
        def verify(self):
            return report["lease_before"]

    monkeypatch.setattr(module, "NativeValidationLeaseVerifier", UnitLeaseVerifier)
    events = []

    class UnitChild:
        pid, returncode = 73191, None
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            events.append(("wait", timeout))
            self.returncode = -signal.SIGTERM
            return self.returncode

    child = UnitChild()

    def spawn(command, **kwargs):
        assert command == ["unit-control-flow-child"]
        assert kwargs["start_new_session"] is True
        events.append(("spawn",))
        return child

    def kill_group(pid, signum):
        assert pid == child.pid and signum == signal.SIGTERM
        # Repeated SIGTERM during bounded cleanup must not terminate the CLI.
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
        signal.raise_signal(signal.SIGTERM)
        events.append(("term",))

    monkeypatch.setattr(subject.subprocess, "Popen", spawn)
    monkeypatch.setattr(subject.os, "killpg", kill_group)
    monkeypatch.setattr(subject.time, "sleep", lambda seconds: signal.raise_signal(signal.SIGTERM))
    previous = signal.getsignal(signal.SIGTERM)
    assert module.main(["--manifest", str(manifest_path), "--output", str(output)]) == 1
    assert signal.getsignal(signal.SIGTERM) == previous
    assert events == [("spawn",), ("term",), ("wait", 10)]
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["status"] == "blocked_engineering_checker"
    assert refusal["reason"] == "native checker interrupted by SIGTERM"
    assert all(refusal[name] is False for name in subject.FALSE)
    failure = subject.load_json((output / "failure-execution-report.json").read_bytes())
    assert failure["returncode"] == -signal.SIGTERM and failure["cleanup_complete"] is True
    assert failure["error_type"] == "SpanClaimAcceptanceError"
    assert failure["evidence"] == {"native-tests.junit.xml": None, "native-events.json": None}
    assert failure["synthetic_junit_or_phases_created"] is False
    assert all(failure[name] is False for name in subject.FALSE)
    assert not any(path.name.startswith("t02-private-native-") for path in output.iterdir())


def test_cli_restores_sigterm_handler_after_success_without_changing_original_handler(tmp_path, monkeypatch, capsys):
    import signal
    module = _cli_module("t02_acceptance_cli_normal_completion_test")
    manifest, report, _, _, _ = fixture()
    path = tmp_path / "manifest.json"
    path.write_bytes(subject.raw(manifest))
    monkeypatch.setenv(module.STATE_ENV, "unit-control-flow-state")
    monkeypatch.setenv(module.POLICY_ENV, report["lease_before"]["policy_sha256"])
    monkeypatch.setattr(module, "NativeValidationLeaseVerifier", lambda state, policy: object())
    previous = signal.getsignal(signal.SIGTERM)

    def unit_runner(*args, **kwargs):
        assert callable(signal.getsignal(signal.SIGTERM))
        assert signal.getsignal(signal.SIGTERM) != previous
        return dict(status="unit_control_flow_fixture", **subject.FALSE)

    monkeypatch.setattr(module, "run_private_checks", unit_runner)
    assert module.main(["--manifest", str(path), "--output", str(tmp_path / "unused")]) == 0
    assert signal.getsignal(signal.SIGTERM) == previous
    assert "unit_control_flow_fixture" in capsys.readouterr().out


def _pytest_entry():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/span_claim_acceptance_test.py"
    spec = importlib.util.spec_from_file_location("t02_acceptance_explicit_pytest_entry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("missing", ["manifest", "output", "both"])
def test_explicit_pytest_entry_missing_environment_fails_without_skipping_or_running(monkeypatch, missing):
    entry = _pytest_entry()
    monkeypatch.setenv(entry.MANIFEST_ENV, "unit-manifest.json")
    monkeypatch.setenv(entry.OUTPUT_ENV, "unit-fresh-output")
    if missing in {"manifest", "both"}:
        monkeypatch.delenv(entry.MANIFEST_ENV)
    if missing in {"output", "both"}:
        monkeypatch.delenv(entry.OUTPUT_ENV)
    monkeypatch.setattr(entry.checker, "main", lambda argv: pytest.fail("missing environment invoked live checker"))
    with pytest.raises(AssertionError, match="explicit T02 manifest"):
        entry.test_span_claim_engineering_acceptance()


@pytest.mark.parametrize("status", [0, 1])
def test_explicit_pytest_entry_forwards_only_closed_paths_and_propagates_cli_refusal(monkeypatch, status):
    entry = _pytest_entry()
    monkeypatch.setenv(entry.MANIFEST_ENV, "unit-manifest.json")
    monkeypatch.setenv(entry.OUTPUT_ENV, "unit-fresh-output")
    seen = []
    def unit_cli(argv):
        seen.append(argv)
        return status
    monkeypatch.setattr(entry.checker, "main", unit_cli)
    if status:
        with pytest.raises(AssertionError, match="native T02 engineering checker refused"):
            entry.test_span_claim_engineering_acceptance()
    else:
        entry.test_span_claim_engineering_acceptance()
    assert seen == [["--manifest", "unit-manifest.json", "--output", "unit-fresh-output"]]


def test_actual_checker_process_is_present_in_observed_ancestry():
    import importlib.util
    import os
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/check_span_claim_acceptance.py"
    spec = importlib.util.spec_from_file_location("t02_acceptance_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert os.getpid() in module.ancestors()


@pytest.mark.parametrize("failure", ["cancelled", "missing", "foreign_owner", "wrong_scope", "wrong_lane", "expired", "children"])
def test_native_lease_verifier_refuses_invalid_observations_without_reserving(tmp_path, monkeypatch, failure):
    import importlib.util
    import json
    import time
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/check_span_claim_acceptance.py"
    spec = importlib.util.spec_from_file_location("t02_acceptance_cli_lease_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = {"fixture": "untrusted private lease unit test"}
    state = tmp_path / "private-scheduler.json"
    state.write_text(json.dumps({"config": config}))
    record = dict(lease_id="fixture-lease", lane="validation", owner_pid=42,
        request_id=module.REQUEST_PREFIX + "unit", expires_at=time.time()+60,
        cpu_slots=1, memory_mb=1536, child_process_slots=2)
    if failure == "foreign_owner": record["owner_pid"] = 99
    if failure == "wrong_scope": record["request_id"] = "unrelated-request"
    if failure == "wrong_lane": record["lane"] = "trainer"
    if failure == "expired": record["expires_at"] = 0
    if failure == "children": record["child_process_slots"] = 1
    class FakeScheduler:
        def active_leases(self): return [] if failure == "missing" else [record]
        def is_cancelled(self, *args, **kwargs): return failure == "cancelled"
    verifier = module.NativeValidationLeaseVerifier.__new__(module.NativeValidationLeaseVerifier)
    verifier.path, verifier.original = state, config
    verifier.lease_id, verifier.policy = "fixture-lease", subject.digest(config)
    verifier.scheduler = FakeScheduler()
    monkeypatch.setattr(module, "ancestors", lambda: {42})
    with pytest.raises(subject.SpanClaimAcceptanceError):
        verifier.verify()

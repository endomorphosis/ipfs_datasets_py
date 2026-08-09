from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest


pytest.importorskip("duckdb")

from scripts.ops import ipfs_datasets_duckdb_quack_program as program


_FIXTURE_SIGNING_KEY = b"manual-gate-fixture-key-never-used-in-production"


def _signed_fixture_input(task_id: str, snapshot: Any) -> bytes:
    body = {
        "schema": "test/manual-gate-signed-decision@1",
        "gate_task_id": task_id,
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "request": {
            "accelerator_commit": "a" * 40,
            "accelerator_tree": "b" * 40,
            "transition": "pin-accelerator-release",
        },
    }
    signature = hmac.new(
        _FIXTURE_SIGNING_KEY,
        program._canonical_json(body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return program._canonical_json({"body": body, "signature": signature}).encode(
        "utf-8"
    )


class _FixtureSignedDecisionAdapter:
    @staticmethod
    def _verify(task_id: str, raw_input: bytes, snapshot: Any) -> dict[str, Any]:
        envelope = program._strict_json_object(
            raw_input.decode("utf-8"), noun="fixture signed decision"
        )
        assert set(envelope) == {"body", "signature"}
        body = envelope["body"]
        assert isinstance(body, dict)
        assert body["gate_task_id"] == task_id
        assert body["plan_root_cid"] == snapshot.plan_root_cid
        assert body["repository_tree_id"] == snapshot.repository_tree_id
        expected = hmac.new(
            _FIXTURE_SIGNING_KEY,
            program._canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(str(envelope["signature"]), expected):
            raise RuntimeError("fixture signed decision signature rejected")
        decision_id = program._manual_gate_receipt_id(
            "fixture-signed-decision", body
        )
        return {
            "schema": "test/manual-gate-independent-signature-proof@1",
            "decision_id": decision_id,
            "signed_input_sha256": "sha256:" + hashlib.sha256(raw_input).hexdigest(),
        }

    def preflight(self, **kwargs: Any) -> dict[str, Any]:
        return self._verify(
            kwargs["task_id"], kwargs["raw_input"], kwargs["snapshot"]
        )

    def verify_execution(self, **kwargs: Any) -> dict[str, Any]:
        proof = self._verify(
            kwargs["task_id"], kwargs["raw_input"], kwargs["snapshot"]
        )
        if kwargs["typed_output"].get("decision_cid") != proof["decision_id"]:
            raise RuntimeError("fixture output is detached from signed decision")
        signed = program._strict_json_object(
            kwargs["raw_input"].decode("utf-8"), noun="fixture signed decision"
        )
        request = signed["body"]["request"]
        if any(
            kwargs["typed_output"].get(key) != request[key]
            for key in ("accelerator_commit", "accelerator_tree")
        ):
            raise RuntimeError("fixture effect differs from signed transition")
        return {
            **proof,
            "typed_output_sha256": "sha256:"
            + hashlib.sha256(
                program._canonical_json(kwargs["typed_output"]).encode("utf-8")
            ).hexdigest(),
        }


@pytest.fixture()
def task_source(tmp_path: Path):
    DuckDBTaskSource, _providers = program._accelerate_imports()
    source = DuckDBTaskSource(tmp_path / "control.duckdb")
    source.materialize(
        program.formal_source("tree:git:manual-gate-fixture"),
        repository_tree_id="tree:git:manual-gate-fixture",
        expected_absent=True,
    )
    return source


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _verifier_repository(root: Path) -> Path:
    verifier = (
        root
        / "scripts/validation/validate_accelerate_duckdb_quack_release.py"
    )
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        "#!/usr/bin/env python3\n# exact committed manual-gate verifier\n",
        encoding="utf-8",
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Manual Gate Test")
    _git(root, "config", "user.email", "manual-gate@example.invalid")
    _git(root, "add", "--", ".")
    _git(root, "commit", "-m", "install release verifier")
    return root


def _complete_owner(source: Any, gate_task_id: str) -> None:
    owner_id = program.MANUAL_GATE_OWNER_TASK_IDS[gate_task_id]
    owner = source.get_task(owner_id)
    assert owner is not None
    if owner.status != "completed":
        source.compare_and_set_status(
            owner_id,
            expected_revision=owner.revision,
            status="completed",
            receipt={"schema": "test/manual-gate-owner-completion@1"},
        )


def _interpreter_attestation() -> dict[str, Any]:
    digest = "sha256:" + "9" * 64
    return {
        "launcher_path": str(program.SEALED_PYTHON_LAUNCHER),
        "launcher_sha256": digest,
        "base_python_path": "/usr/bin/python3.12",
        "base_python_sha256": digest,
        "environment_receipt_id": "environment:test-manual-gate",
        "environment_root": str(program.EXPECTED_ENV_ROOT),
        "python_version": "3.12.3",
    }


def _release_output(
    snapshot: Any, *, expires_at: datetime, decision_id: str
) -> dict[str, Any]:
    del snapshot
    return {
        "schema": program._RELEASE_VERIFICATION_SCHEMA,
        "accepted": True,
        "accelerator_commit": "a" * 40,
        "accelerator_tree": "b" * 40,
        "release_receipt_cid": "release:test",
        "cutover_receipt_cid": "cutover:test",
        "store_generation": "generation:test",
        "schema_checksum": "sha256:" + "c" * 64,
        "quack_profile": "quack-profile:test",
        "decision_cid": decision_id,
        "expires_at": expires_at.isoformat(),
    }


def _execution_receipt(
    task_id: str,
    *,
    input_capture: Mapping[str, Any],
    snapshot: Any,
    verifier_attestation: Mapping[str, Any],
    interpreter_attestation: Mapping[str, Any],
    raw_input: bytes,
    decision_preflight: Mapping[str, Any],
    checked_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    typed_output = _release_output(
        snapshot,
        expires_at=expires_at,
        decision_id=str(decision_preflight["decision_id"]),
    )
    argv = list(
        program._manual_gate_verifier_argv(
            task_id,
            input_path="/proc/self/fd/17",
            snapshot=snapshot,
            attestation=verifier_attestation,
        )
    )
    environment = {
        **program._sealed_python_environment(),
        "IPFS_DATASETS_DQK_ENV_ROOT": str(program.EXPECTED_ENV_ROOT),
        "LANG": "C.UTF-8",
    }
    observed_cmdline = b"\0".join(item.encode("utf-8") for item in argv) + b"\0"
    stdout = program._canonical_json(typed_output).encode("utf-8")
    stderr = b""
    decision_verification = _FixtureSignedDecisionAdapter().verify_execution(
        task_id=task_id,
        raw_input=raw_input,
        typed_output=typed_output,
        snapshot=snapshot,
    )
    blob_store = program._manual_gate_blob_store()
    receipt: dict[str, Any] = {
        "schema": program.MANUAL_GATE_EXECUTION_SCHEMA,
        "gate_task_id": task_id,
        "owner_task_id": program.MANUAL_GATE_OWNER_TASK_IDS[task_id],
        "authority_effect_id": program.MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id],
        "input_capture": dict(input_capture),
        "decision_preflight": dict(decision_preflight),
        "decision_verification": decision_verification,
        "verifier": dict(verifier_attestation),
        "interpreter": dict(interpreter_attestation),
        "argv": argv,
        "environment": environment,
        "stdin_sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        "process": {
            "pid": 17001,
            "boot_id": "boot-manual-gate",
            "start_ticks": 314159,
            "cmdline_sha256": "sha256:"
            + hashlib.sha256(observed_cmdline).hexdigest(),
            "argv": argv,
            "returncode": 0,
            "started_at": (checked_at - timedelta(seconds=1)).isoformat(),
            "finished_at": checked_at.isoformat(),
            "stdout_sha256": "sha256:" + hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": "sha256:" + hashlib.sha256(stderr).hexdigest(),
            "stdout_blob": blob_store.put("stdout", stdout),
            "stderr_blob": blob_store.put("stderr", stderr),
        },
        "typed_output": typed_output,
        "effect_receipt_id": typed_output["decision_cid"],
        "freshness_checked_at": checked_at.isoformat(),
    }
    receipt["execution_blob"] = blob_store.put(
        "execution", program._canonical_json(receipt).encode("utf-8")
    )
    receipt["execution_id"] = program._manual_gate_receipt_id(
        "manual-gate-verifier-execution", receipt
    )
    return receipt


def _configure_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: Any,
) -> None:
    repository = _verifier_repository(tmp_path / "verifier-repository")
    lifecycle_root = tmp_path / "runtime/manual-gates"
    monkeypatch.setattr(program, "REPO_ROOT", repository)
    monkeypatch.setattr(program, "MANUAL_GATE_LIFECYCLE_ROOT", lifecycle_root)
    monkeypatch.setattr(
        program,
        "MANUAL_GATE_LIFECYCLE_LOCK",
        lifecycle_root / ".lifecycle.lock",
    )
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "runtime/master")
    monkeypatch.setattr(
        program, "MASTER_PID", tmp_path / "runtime/master/supervisor.pid"
    )
    monkeypatch.setattr(
        program,
        "MASTER_IDENTITY",
        tmp_path / "runtime/master/supervisor.identity.json",
    )
    monkeypatch.setattr(program, "SEALED_PYTHON_LAUNCHER", Path("/sealed/dqk-python"))
    monkeypatch.setattr(
        program,
        "_manual_gate_interpreter_attestation",
        _interpreter_attestation,
    )
    monkeypatch.setattr(program, "_source", lambda require=True: source)
    monkeypatch.setattr(
        program,
        "_manual_gate_task_authority_adapter",
        lambda _task_id: _FixtureSignedDecisionAdapter(),
    )

    def prepare_effect(
        task_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        value = {
            "schema": "test/manual-gate-effect-intent@1",
            "gate_task_id": task_id,
            "lifecycle_id": kwargs["journal"]["lifecycle_id"],
            "operation_id": kwargs["journal"]["lifecycle_id"],
            "execution_id": kwargs["execution"]["execution_id"],
        }
        value["intent_id"] = program._manual_gate_receipt_id(
            "test-manual-gate-effect-intent", value
        )
        return value

    def apply_effect(task_id: str, **kwargs: Any) -> dict[str, Any]:
        value = {
            "schema": "test/manual-gate-effect-receipt@1",
            "gate_task_id": task_id,
            "intent_id": kwargs["journal"]["effect_intent"]["intent_id"],
        }
        value["receipt_id"] = program._manual_gate_receipt_id(
            "test-manual-gate-effect-receipt", value
        )
        return value

    def validate_effect(
        task_id: str, *, effect_receipt: Mapping[str, Any], effect_intent: Mapping[str, Any], snapshot: Any, **_kwargs: Any
    ) -> None:
        del snapshot
        assert effect_receipt["gate_task_id"] == task_id
        assert effect_receipt["intent_id"] == effect_intent["intent_id"]
        expected = {
            key: value for key, value in effect_receipt.items() if key != "receipt_id"
        }
        assert effect_receipt["receipt_id"] == program._manual_gate_receipt_id(
            "test-manual-gate-effect-receipt", expected
        )

    monkeypatch.setattr(program, "_prepare_manual_gate_effect", prepare_effect)
    monkeypatch.setattr(program, "_apply_manual_gate_effect", apply_effect)
    monkeypatch.setattr(
        program, "_validate_manual_gate_effect_receipt", validate_effect
    )
    monkeypatch.setattr(
        program,
        "_acquire_or_adopt_manual_gate_effect_leases",
        lambda _journal: ({"fixture_lease": "parent"}, {"fixture_lease": "accelerator"}),
    )
    monkeypatch.setattr(
        program,
        "_ensure_manual_gate_effect_custody",
        lambda journal: (
            tuple(
                journal.get("checkout_leases")
                or ({"fixture_lease": "parent"}, {"fixture_lease": "accelerator"})
            ),
            None,
        ),
    )
    monkeypatch.setattr(program, "_assert_manual_gate_effect_leases", lambda _journal: None)
    monkeypatch.setattr(
        program,
        "_bind_manual_gate_relaunch_custodian",
        lambda journal, _relaunch: tuple(journal.get("checkout_leases") or ()),
    )
    monkeypatch.setattr(
        program, "_release_manual_gate_effect_leases", lambda _journal: []
    )
    monkeypatch.setattr(
        program,
        "_validate_manual_gate_checkout_release",
        lambda _journal: "sha256:" + "7" * 64,
    )


def test_manual_gate_inputs_are_strict_bounded_and_nofollow(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text('{"decision":"approve"}', encoding="utf-8")
    capture, raw = program._manual_gate_input_capture(valid)
    assert raw == b'{"decision":"approve"}'
    assert capture["sha256"].startswith("sha256:")

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"decision":"approve","decision":"deny"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="duplicate key"):
        program._manual_gate_input_capture(duplicate)

    non_finite = tmp_path / "nan.json"
    non_finite.write_text('{"score":NaN}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="non-finite"):
        program._manual_gate_input_capture(non_finite)

    link = tmp_path / "link.json"
    link.symlink_to(valid)
    with pytest.raises(RuntimeError, match="without symlinks"):
        program._manual_gate_input_capture(link)

    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="without symlinks"):
        program._manual_gate_input_capture(linked_parent / "valid.json")


def test_manual_tasks_declare_typed_non_file_authority_effects() -> None:
    tasks = {str(item["task_id"]): item for item in program.TASKS}
    for task_id in program.MANUAL_GATE_TASK_IDS:
        effects = [
            effect
            for effect in tasks[task_id]["effects"]
            if effect["fluent_id"] == program.MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id]
        ]
        assert len(effects) == 1
        assert "path" not in effects[0]
        assert effects[0]["operation"] == "assign"
        assert effects[0]["value"].startswith(
            "ipfs_datasets_py/manual-gate-authority-effect@1:"
        )
        file_effect_paths = [
            str(effect["path"])
            for effect in tasks[task_id]["effects"]
            if str(effect.get("path") or "")
        ]
        assert tasks[task_id]["scope_paths"] == file_effect_paths


@pytest.mark.parametrize(
    "crash_phase",
    (
        "PREPARED",
        "DRAIN_PREPARED",
        "DRAINED",
        "EXECUTION_PREPARED",
        "EFFECT_PREPARED",
        "EFFECT_APPLIED",
        "CAS_COMMITTED",
        "RELAUNCHED",
        "RELEASE_PREPARED",
        "RELEASED",
    ),
)
def test_manual_gate_lifecycle_replays_every_boundary_exactly_once(
    crash_phase: str,
    task_source: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_lifecycle(monkeypatch, tmp_path, task_source)
    _complete_owner(task_source, program.RELEASE_GATE_TASK_ID)
    gate = task_source.get_task(program.RELEASE_GATE_TASK_ID)
    assert gate is not None and gate.status == "blocked"
    receipt_file = tmp_path / "release.json"
    receipt_file.write_bytes(
        _signed_fixture_input(
            program.RELEASE_GATE_TASK_ID, task_source.snapshot()
        )
    )
    execute_calls = 0
    launched = False
    relaunch_calls = 0
    crashed = False

    def execute(task_id: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal execute_calls
        execute_calls += 1
        checked_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        return _execution_receipt(
            task_id,
            input_capture=kwargs["input_capture"],
            snapshot=kwargs["snapshot"],
            verifier_attestation=kwargs["verifier_attestation"],
            interpreter_attestation=kwargs["interpreter_attestation"],
            raw_input=kwargs["raw_input"],
            decision_preflight=kwargs["decision_preflight"],
            checked_at=checked_at,
            expires_at=checked_at + timedelta(hours=1),
        )

    def relaunch(_journal: Mapping[str, Any], _source: Any) -> dict[str, Any]:
        nonlocal launched, relaunch_calls
        relaunch_calls += 1
        if not launched:
            launched = True
        return {
            "kind": "adopted" if relaunch_calls > 1 else "launched",
            "pid": 18001,
            "boot_id": "boot-relaunch",
            "start_ticks": 271828,
            "cmdline_sha256": "sha256:" + "8" * 64,
        }

    def crash(selected: str) -> None:
        nonlocal crashed
        if selected == crash_phase and not crashed:
            crashed = True
            raise RuntimeError(f"crash:{selected}")

    monkeypatch.setattr(program, "_manual_gate_crash_boundary", crash)
    with pytest.raises(RuntimeError, match=f"crash:{crash_phase}"):
        program._run_manual_gate_lifecycle(
            program.RELEASE_GATE_TASK_ID,
            receipt_file=receipt_file,
            expected_task_revision=gate.revision,
            execute_verifier=execute,
            relaunch_runtime=relaunch,
        )
    interim_admitted, interim_detail = program._manual_gate_restart_admission(
        task_source
    )
    if crash_phase == "RELEASED":
        assert interim_admitted, interim_detail
    else:
        assert not interim_admitted
        assert "manual_gate_lifecycle_incomplete" in interim_detail
    released = program._run_manual_gate_lifecycle(
        program.RELEASE_GATE_TASK_ID,
        receipt_file=receipt_file,
        expected_task_revision=gate.revision,
        execute_verifier=execute,
        relaunch_runtime=relaunch,
    )
    assert released["schema"] == program.MANUAL_GATE_RELEASE_RECEIPT_SCHEMA
    assert execute_calls == 1
    assert launched is True
    assert relaunch_calls <= 2
    completed = task_source.get_task(program.RELEASE_GATE_TASK_ID)
    assert completed is not None and completed.status == "completed"
    admitted, detail = program._manual_gate_restart_admission(task_source)
    assert admitted, detail

    # Replays use historical content evidence. They neither execute a now-dead
    # process nor re-check the decision against current wall-clock time.
    replay = program._run_manual_gate_lifecycle(
        program.RELEASE_GATE_TASK_ID,
        receipt_file=receipt_file,
        expected_task_revision=gate.revision,
        execute_verifier=lambda *_args, **_kwargs: pytest.fail("effect replayed"),
        relaunch_runtime=lambda *_args, **_kwargs: pytest.fail("relaunch replayed"),
    )
    assert replay == released


def test_bare_or_forged_gate_cas_never_releases_descendants(
    task_source: Any,
) -> None:
    before_snapshot, before_hold = program._manual_gate_hold_projection(task_source)
    assert "DQK-051" in before_hold["held_task_aliases"]
    assert program.RELEASE_VERIFIER_TASK_ID not in before_hold["held_task_aliases"]
    gate = task_source.get_task(program.RELEASE_GATE_TASK_ID)
    assert gate is not None
    task_source.compare_and_set_status(
        gate.task_id,
        expected_revision=gate.revision,
        status="completed",
        receipt={"schema": "forged/generic-cas@1", "accepted": True},
    )
    after_snapshot, after_hold = program._manual_gate_hold_projection(task_source)
    assert after_snapshot.plan_root_cid == before_snapshot.plan_root_cid
    assert "DQK-051" in after_hold["held_task_aliases"]
    assert after_hold["held_set_sha256"] == before_hold["held_set_sha256"]
    admitted, detail = program._manual_gate_restart_admission(task_source)
    assert not admitted
    assert "manual_gate_authenticated_execution_missing" in detail


def test_status_and_doctor_report_a_healthy_authorization_wait(
    task_source: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for row in task_source.query("tasks", limit=1_000):
        alias = str(row["task_alias"])
        if alias in program.MANUAL_GATE_TASK_IDS:
            continue
        task = task_source.get_task(alias)
        assert task is not None
        if task.status != "completed":
            task_source.compare_and_set_status(
                alias,
                expected_revision=task.revision,
                status="completed",
                receipt={"schema": "test/code-task-completion@1"},
            )
    runtime = tmp_path / "status-runtime"
    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "STATE_ROOT", runtime / "state")
    monkeypatch.setattr(program, "MASTER_PID", runtime / "master/supervisor.pid")
    monkeypatch.setattr(
        program, "MASTER_IDENTITY", runtime / "master/supervisor.identity.json"
    )
    monkeypatch.setattr(program, "MASTER_LOG", runtime / "master/supervisor.log")
    monkeypatch.setattr(program, "MANUAL_GATE_LIFECYCLE_ROOT", runtime / "manual-gates")
    monkeypatch.setattr(
        program,
        "MANUAL_GATE_LIFECYCLE_LOCK",
        runtime / "manual-gates/.lifecycle.lock",
    )
    monkeypatch.setattr(program, "_source", lambda require=True: task_source)
    monkeypatch.setattr(
        program,
        "_external_dqp_status",
        lambda: {
            "master_alive": True,
            "lane_count": 2,
            "expected_lane_count": 2,
            "stale_or_unbound_lanes": [],
            "completed_count": 39,
            "task_count": 39,
            "release_status": "completed",
        },
    )
    payload = program.task_status(task_source)
    assert payload["authorization_wait"] is True
    assert payload["authorization_evidence_failed"] is False
    assert set(payload["authorization_incomplete_gate_task_ids"]) == set(
        program.MANUAL_GATE_TASK_IDS
    )
    assert payload["ready_task_ids"] == []
    assert program.cmd_doctor(SimpleNamespace(stale_seconds=1_200.0)) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["healthy"] is True
    pending = [
        item
        for item in doctor["findings"]
        if item["kind"] == "manual_authorization_pending"
    ]
    assert len(pending) >= len(program.MANUAL_GATE_TASK_IDS)


def test_expiry_is_checked_at_execution_not_forever(
    task_source: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_lifecycle(monkeypatch, tmp_path, task_source)
    snapshot = task_source.snapshot()
    receipt_file = tmp_path / "release.json"
    receipt_file.write_bytes(
        _signed_fixture_input(program.RELEASE_GATE_TASK_ID, snapshot)
    )
    input_capture, raw = program._manual_gate_input_capture(receipt_file)
    with program._manual_gate_lock_context():
        input_capture = program._manual_gate_bound_input_capture(input_capture, raw)
    verifier = program._manual_gate_verifier_attestation(program.RELEASE_GATE_TASK_ID)
    interpreter = _interpreter_attestation()
    decision_preflight = _FixtureSignedDecisionAdapter().preflight(
        task_id=program.RELEASE_GATE_TASK_ID,
        raw_input=raw,
        snapshot=snapshot,
    )
    checked_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    expired = _execution_receipt(
        program.RELEASE_GATE_TASK_ID,
        input_capture=input_capture,
        snapshot=snapshot,
        verifier_attestation=verifier,
        interpreter_attestation=interpreter,
        raw_input=raw,
        decision_preflight=decision_preflight,
        checked_at=checked_at,
        expires_at=checked_at - timedelta(microseconds=1),
    )
    with pytest.raises(RuntimeError, match="expired at execution"):
        program._validate_manual_gate_execution_receipt(
            program.RELEASE_GATE_TASK_ID,
            expired,
            snapshot=snapshot,
            input_capture=input_capture,
        )

    historically_valid = _execution_receipt(
        program.RELEASE_GATE_TASK_ID,
        input_capture=input_capture,
        snapshot=snapshot,
        verifier_attestation=verifier,
        interpreter_attestation=interpreter,
        raw_input=raw,
        decision_preflight=decision_preflight,
        checked_at=checked_at,
        expires_at=checked_at + timedelta(microseconds=1),
    )
    program._validate_manual_gate_execution_receipt(
        program.RELEASE_GATE_TASK_ID,
        historically_valid,
        snapshot=snapshot,
        input_capture=input_capture,
    )


def test_duplicate_and_non_finite_execution_objects_fail_closed(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate-output.json"
    duplicate.write_text('{"accepted":true,"accepted":true}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="duplicate key"):
        program._bounded_json_file(duplicate)

    non_finite = tmp_path / "infinite-output.json"
    non_finite.write_text('{"score":Infinity}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="non-finite"):
        program._bounded_json_file(non_finite)


def test_manual_gate_authority_module_is_bootstrap_bound_and_provider_protected() -> None:
    relative = program.MANUAL_GATE_AUTHORITY_MODULE.relative_to(
        program.REPO_ROOT
    ).as_posix()
    evidence = program._bootstrap_artifact_evidence()
    assert relative in evidence
    assert evidence[relative] == program._sha256_file(
        program.MANUAL_GATE_AUTHORITY_MODULE
    )
    assert relative in program._implementation_protected_paths()
    assert all(
        relative not in tuple(str(item) for item in task.get("outputs") or ())
        for task in program.TASKS
    )


def test_direct_program_entry_loads_exact_sibling_with_foreign_scripts_package(
    tmp_path: Path,
) -> None:
    foreign = tmp_path / "foreign"
    (foreign / "scripts/ops").mkdir(parents=True)
    (foreign / "scripts/__init__.py").write_text("# foreign\n", encoding="utf-8")
    (foreign / "scripts/ops/__init__.py").write_text("# foreign\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(program.__file__)), "preflight", "--json"],
        cwd=program.REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(foreign)},
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    combined = result.stdout + result.stderr
    assert "cannot import name 'ipfs_datasets_duckdb_quack_manual_gate'" not in combined
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert {str(item.get("name")) for item in payload} >= {
        "isolated_execution_environment",
        "manual_gate_authenticated_execution",
    }


def test_missing_committed_verifier_fails_closed_with_materialization_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = tmp_path / "missing-verifier"
    repository.mkdir()
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Manual Gate Test")
    _git(repository, "config", "user.email", "manual-gate@example.invalid")
    _git(repository, "add", "--", "README.md")
    _git(repository, "commit", "-m", "no verifier yet")
    monkeypatch.setattr(program, "REPO_ROOT", repository)
    with pytest.raises(RuntimeError, match="manual_gate_verifier_not_materialized"):
        program._manual_gate_verifier_attestation(program.RELEASE_GATE_TASK_ID)


@pytest.mark.parametrize("stream", ("stdout", "stderr"))
def test_verifier_pipe_is_killed_at_the_incremental_byte_bound(stream: str) -> None:
    descriptor = "sys.stdout.buffer" if stream == "stdout" else "sys.stderr.buffer"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import sys; {descriptor}.write(b'x' * 131073); {descriptor}.flush()",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with pytest.raises(RuntimeError, match=f"{stream} exceeded its byte bound"):
        program._bounded_manual_gate_process_output(
            process, maximum_bytes=128 * 1024, timeout_seconds=10
        )
    assert process.poll() is not None


def test_verifier_pipes_share_one_combined_memory_bound() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(b'o' * 71680); sys.stdout.buffer.flush(); "
                "sys.stderr.buffer.write(b'e' * 71680); sys.stderr.buffer.flush()"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with pytest.raises(RuntimeError, match="combined output exceeded"):
        program._bounded_manual_gate_process_output(
            process, maximum_bytes=128 * 1024, timeout_seconds=10
        )
    assert process.poll() is not None


def test_content_blobs_persist_exact_bytes_nofollow_and_no_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = tmp_path / "manual-gates"
    lifecycle.mkdir(mode=0o700)
    store = program.manual_gate_authority.ContentBlobStore(lifecycle)
    raw = b'{"signed":"exact-input"}'
    record = store.put("input", raw)
    blob_path = lifecycle / str(record["relative_path"])
    assert blob_path.read_bytes() == raw
    assert store.read(record, expected_kind="input") == raw
    assert store.put("input", raw) == record

    blob_path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserve")
    blob_path.symlink_to(outside)
    with pytest.raises(RuntimeError, match="without symlinks|publication failed"):
        store.put("input", raw)
    assert outside.read_bytes() == b"preserve"
    blob_path.unlink()

    original_link = program.manual_gate_authority.os.link

    def race_link(*args: Any, **kwargs: Any) -> None:
        blob_path.write_bytes(b"counterfeit")
        blob_path.chmod(0o600)
        original_link(*args, **kwargs)

    monkeypatch.setattr(program.manual_gate_authority.os, "link", race_link)
    with pytest.raises(RuntimeError, match="different bytes"):
        store.put("input", raw)
    assert blob_path.read_bytes() == b"counterfeit"


@pytest.mark.parametrize(
    "task_id",
    (program.PROMOTION_GATE_TASK_ID, program.RUNTIME_ACTIVATION_GATE_TASK_ID),
)
def test_effectful_manual_gates_block_before_any_verifier_subprocess(
    task_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        program.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("effectful verifier was invoked"),
    )
    with pytest.raises(
        RuntimeError, match=f"manual_gate_effect_adapter_not_materialized:{task_id}"
    ):
        program._execute_manual_gate_verifier(
            task_id,
            raw_input=b"{}",
            input_capture={},
            snapshot=SimpleNamespace(plan_root_cid="plan", repository_tree_id="tree"),
            verifier_attestation={},
            interpreter_attestation={},
            decision_preflight={},
        )


def _nested_gitlink_repositories(tmp_path: Path) -> tuple[Path, Path, str, str, tuple[str, ...]]:
    parent = tmp_path / "parent"
    accelerator = parent / "ipfs_accelerate_py"
    accelerator.mkdir(parents=True)
    _git(accelerator, "init", "-b", "main")
    _git(accelerator, "config", "user.name", "Manual Gate Test")
    _git(accelerator, "config", "user.email", "manual-gate@example.invalid")
    (accelerator / "release.txt").write_text("old\n", encoding="utf-8")
    _git(accelerator, "add", "--", "release.txt")
    _git(accelerator, "commit", "-m", "old accelerator")
    old_commit = _git(accelerator, "rev-parse", "HEAD")

    _git(parent, "init", "-b", "main")
    _git(parent, "config", "user.name", "Manual Gate Test")
    _git(parent, "config", "user.email", "manual-gate@example.invalid")
    protected = (
        "scripts/ops/program.py",
        "scripts/ops/manual_gate.py",
        "requirements/bootstrap.lock",
    )
    for relative in protected:
        selected = parent / relative
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text(relative + "\n", encoding="utf-8")
    _git(parent, "add", "--", *protected, "ipfs_accelerate_py")
    _git(parent, "commit", "-m", "parent with old accelerator")

    (accelerator / "release.txt").write_text("accepted\n", encoding="utf-8")
    _git(accelerator, "add", "--", "release.txt")
    _git(accelerator, "commit", "-m", "accepted accelerator")
    new_commit = _git(accelerator, "rev-parse", "HEAD")
    new_tree = _git(accelerator, "rev-parse", "HEAD^{tree}")
    assert old_commit != new_commit
    return parent, accelerator, old_commit, new_commit, protected


def _checkout_release_store(tmp_path: Path) -> Any:
    root = tmp_path / "manual-gate-runtime"
    root.mkdir(mode=0o700)
    return program.manual_gate_authority.ContentBlobStore(root)


def test_checkout_lease_is_native_daemon_compatible_and_cross_process_adoptable(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    operation_id = "sha256:" + "3" * 64
    child_code = "\n".join(
        (
            "import json, sys",
            "from pathlib import Path",
            "from scripts.ops import ipfs_datasets_duckdb_quack_program as p",
            "records = p.manual_gate_authority.acquire_or_adopt_checkout_leases(",
            "    {'parent': Path(sys.argv[1]), 'accelerator': Path(sys.argv[2])},",
            "    operation_id=sys.argv[3], checkout_module=p._manual_gate_checkout_module())",
            "print(json.dumps({'records': records}, sort_keys=True))",
        )
    )
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            str(parent),
            str(accelerator),
            operation_id,
        ],
        cwd=program.REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                (str(program.REPO_ROOT), str(program.ACCELERATE_ROOT))
            ),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    child_records = tuple(json.loads(child.stdout)["records"])
    adopted = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=program._manual_gate_checkout_module(),
        expected_records=child_records,
    )
    assert all(record["generation"] == 2 for record in adopted)
    assert all(record["owner_history"][:1] == item["owner_history"] for record, item in zip(adopted, child_records, strict=True))

    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        PortalImplementationDaemon,
    )

    daemon = object.__new__(PortalImplementationDaemon)
    daemon.state_path = tmp_path / "lane/state.json"
    assert all(daemon._implementation_lock_owner_is_active(record) for record in adopted)
    program.manual_gate_authority.release_checkout_leases(
        adopted,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:00:00+00:00",
        checkout_module=program._manual_gate_checkout_module(),
        blob_store=_checkout_release_store(tmp_path),
    )


def test_checkout_lease_relaunch_custodian_remains_native_daemon_visible(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "d" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    custodian = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "multi_supervisor_runner",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        identity = None
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and custodian.poll() is None:
            identity = program.manual_gate_authority._process_identity(custodian.pid)
            if identity is not None:
                break
            time.sleep(0.01)
        assert identity is not None
        bound = program.manual_gate_authority.bind_checkout_leases_to_custodian(
            records,
            custodian=identity,
            owner_script=program.manual_gate_authority.compatibility_owner_script(
                identity
            ),
            checkout_module=checkout_module,
        )
        program.manual_gate_authority.assert_checkout_leases(
            bound,
            checkout_module=checkout_module,
            expected_custodian=identity,
        )
        from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
            PortalImplementationDaemon,
        )

        daemon = object.__new__(PortalImplementationDaemon)
        daemon.state_path = tmp_path / "lane/state.json"
        activity = tuple(
            daemon._implementation_lock_owner_is_active(record) for record in bound
        )
        assert all(activity)
    finally:
        custodian.terminate()
        custodian.wait(timeout=10)
    program.manual_gate_authority.release_checkout_leases(
        bound,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:00:30+00:00",
        checkout_module=checkout_module,
        blob_store=_checkout_release_store(tmp_path),
    )


def test_program_checkout_custodian_covers_master_launch_window(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "9" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    process, identity, bound_records = program._start_manual_gate_checkout_custodian(
        {
            "gate_task_id": program.RELEASE_GATE_TASK_ID,
            "checkout_leases": list(records),
        }
    )
    assert process is not None
    assert identity is not None
    bound = tuple(
        program.manual_gate_authority._read_lease(Path(record["lock_path"]))
        for record in bound_records
    )
    assert all(record is not None for record in bound)
    exact_bound = tuple(dict(record) for record in bound if record is not None)
    try:
        program.manual_gate_authority.assert_checkout_leases(
            exact_bound,
            checkout_module=checkout_module,
            expected_custodian=identity,
        )
        from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
            PortalImplementationDaemon,
        )

        daemon = object.__new__(PortalImplementationDaemon)
        daemon.state_path = tmp_path / "lane/state.json"
        assert all(
            daemon._implementation_lock_owner_is_active(record)
            for record in exact_bound
        )
    finally:
        program._retire_manual_gate_checkout_custodian(identity)
    program.manual_gate_authority.release_checkout_leases(
        exact_bound,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:00:45+00:00",
        checkout_module=checkout_module,
        blob_store=_checkout_release_store(tmp_path),
    )


def test_checkout_custodian_survives_lifecycle_owner_crash_and_is_adopted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    released_checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "8" * 64
    child_code = "\n".join(
        (
            "import json, os, sys",
            "from pathlib import Path",
            "from scripts.ops import ipfs_datasets_duckdb_quack_program as program",
            "released_checkout_module = program._manual_gate_checkout_module()",
            "program.REPO_ROOT = Path(sys.argv[1]).resolve()",
            "program.ACCELERATE_ROOT = Path(sys.argv[2]).resolve()",
            "program._manual_gate_checkout_module = lambda: released_checkout_module",
            "records, custodian = program._ensure_manual_gate_effect_custody({",
            "    'gate_task_id': program.RELEASE_GATE_TASK_ID,",
            "    'lifecycle_id': sys.argv[3],",
            "    'checkout_leases': [],",
            "})",
            "print(json.dumps({'records': records, 'custodian': custodian}, sort_keys=True))",
            "sys.stdout.flush()",
            "os._exit(0)",
        )
    )
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            str(parent),
            str(accelerator),
            operation_id,
        ],
        cwd=program.REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                (str(program.REPO_ROOT), str(program.ACCELERATE_ROOT))
            ),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    payload = json.loads(child.stdout.strip().splitlines()[-1])
    records = tuple(payload["records"])
    custodian = dict(payload["custodian"])
    assert program._identity_is_live(custodian)
    monkeypatch.setattr(program, "REPO_ROOT", parent)
    monkeypatch.setattr(program, "ACCELERATE_ROOT", accelerator)
    monkeypatch.setattr(
        program,
        "_manual_gate_checkout_module",
        lambda: released_checkout_module,
    )
    held: tuple[dict[str, Any], ...] = ()
    try:
        held, recovered = program._ensure_manual_gate_effect_custody(
            {
                "gate_task_id": program.RELEASE_GATE_TASK_ID,
                "lifecycle_id": operation_id,
                "checkout_leases": list(records),
                "checkout_custodian": custodian,
            }
        )
        assert recovered == custodian
        assert tuple(held) == records
        from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
            PortalImplementationDaemon,
        )

        daemon = object.__new__(PortalImplementationDaemon)
        daemon.state_path = tmp_path / "lane/state.json"
        assert all(
            daemon._implementation_lock_owner_is_active(record) for record in held
        )
    finally:
        program._retire_manual_gate_checkout_custodian(custodian)
    program.manual_gate_authority.release_checkout_leases(
        held or records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:00:50+00:00",
        checkout_module=program._manual_gate_checkout_module(),
        blob_store=_checkout_release_store(tmp_path),
    )


def test_manual_gate_refuses_unowned_live_mutator_before_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "bound-repository"
    runtime = tmp_path / "runtime"
    repository.mkdir()
    runtime.mkdir()
    monkeypatch.setattr(program, "REPO_ROOT", repository)
    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "MASTER_PID", runtime / "master/supervisor.pid")
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "implementation_daemon",
            str(repository),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        with pytest.raises(RuntimeError, match="live mutators"):
            program._manual_gate_runtime_drain_basis("sha256:" + "a" * 64)
    finally:
        child.terminate()
        child.wait(timeout=10)
    basis = program._manual_gate_runtime_drain_basis("sha256:" + "a" * 64)
    drained = program._drain_manual_gate_runtime(basis)
    program._validate_manual_gate_runtime_drained(
        "sha256:" + "a" * 64, basis, drained
    )


def test_dqk056_gitlink_pin_holds_replays_and_releases_exact_checkout_leases(
    tmp_path: Path,
) -> None:
    parent, accelerator, old_commit, new_commit, protected = (
        _nested_gitlink_repositories(tmp_path)
    )
    new_tree = _git(accelerator, "rev-parse", "HEAD^{tree}")
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "4" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    intent = program.manual_gate_authority.prepare_gitlink_pin(
        parent=parent,
        accelerator=accelerator,
        target_branch="main",
        desired_commit=new_commit,
        desired_tree=new_tree,
        operation_id=operation_id,
        checkout_leases=records,
        checkout_module=checkout_module,
        protected_paths=protected,
    )
    receipt = program.manual_gate_authority.apply_or_rederive_gitlink_pin(
        parent=parent, intent=intent
    )
    # Crash-after-effect/before-CAS replay adopts the same still-held leases
    # and derives the same isolated effect rather than committing again.
    replayed_records = (
        program.manual_gate_authority.acquire_or_adopt_checkout_leases(
            {"parent": parent, "accelerator": accelerator},
            operation_id=operation_id,
            checkout_module=checkout_module,
            expected_records=records,
        )
    )
    assert replayed_records == records
    replayed = program.manual_gate_authority.apply_or_rederive_gitlink_pin(
        parent=parent, intent=intent
    )
    assert replayed == receipt
    program.manual_gate_authority.validate_gitlink_pin_receipt(
        parent=parent,
        accelerator=accelerator,
        receipt=receipt,
        intent=intent,
    )
    store = _checkout_release_store(tmp_path)
    released = program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:00:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )
    assert len(released) == 2
    assert (
        program.manual_gate_authority.release_checkout_leases(
            records,
            operation_id=operation_id,
            release_prepared_at="2026-08-09T12:00:00+00:00",
            checkout_module=checkout_module,
            blob_store=store,
        )
        == released
    )
    assert _git(parent, "ls-tree", "HEAD", "--", "ipfs_accelerate_py").split()[2] == new_commit

    second_operation = "sha256:" + "5" * 64
    second = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=second_operation,
        checkout_module=checkout_module,
    )
    with pytest.raises(RuntimeError, match="externally pre-pinned"):
        program.manual_gate_authority.prepare_gitlink_pin(
            parent=parent,
            accelerator=accelerator,
            target_branch="main",
            desired_commit=new_commit,
            desired_tree=new_tree,
            operation_id=second_operation,
            checkout_leases=second,
            checkout_module=checkout_module,
            protected_paths=protected,
        )
    program.manual_gate_authority.release_checkout_leases(
        second,
        operation_id=second_operation,
        release_prepared_at="2026-08-09T12:01:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )

    _git(
        parent,
        "update-index",
        "--cacheinfo",
        f"160000,{old_commit},ipfs_accelerate_py",
    )
    _git(parent, "commit", "-m", "revert accelerator pin")
    with pytest.raises(RuntimeError, match="reverted or replaced"):
        program.manual_gate_authority.validate_gitlink_pin_receipt(
            parent=parent,
            accelerator=accelerator,
            receipt=receipt,
            intent=intent,
        )


def test_dqk056_checkout_lease_blocks_foreign_live_owner_and_symlink(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    checkout_module = program._manual_gate_checkout_module()
    first_operation = "sha256:" + "6" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=first_operation,
        checkout_module=checkout_module,
    )
    with pytest.raises(RuntimeError, match="foreign checkout lease|live checkout lease"):
        program.manual_gate_authority.acquire_or_adopt_checkout_leases(
            {"parent": parent, "accelerator": accelerator},
            operation_id="sha256:" + "8" * 64,
            checkout_module=checkout_module,
        )
    store = _checkout_release_store(tmp_path)
    program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=first_operation,
        release_prepared_at="2026-08-09T12:02:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )
    parent_lock = Path(checkout_module.checkout_mutation_lock_path(parent))
    outside = tmp_path / "outside-lease"
    outside.write_text("do-not-touch", encoding="utf-8")
    parent_lock.symlink_to(outside)
    with pytest.raises(RuntimeError, match="without symlinks"):
        program.manual_gate_authority.acquire_or_adopt_checkout_leases(
            {"parent": parent, "accelerator": accelerator},
            operation_id="sha256:" + "9" * 64,
            checkout_module=checkout_module,
        )
    assert outside.read_text(encoding="utf-8") == "do-not-touch"


def test_dqk056_prepare_apply_race_and_missing_lease_fail_closed(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, new_commit, protected = (
        _nested_gitlink_repositories(tmp_path)
    )
    desired_tree = _git(accelerator, "rev-parse", "HEAD^{tree}")
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "a" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    intent = program.manual_gate_authority.prepare_gitlink_pin(
        parent=parent,
        accelerator=accelerator,
        target_branch="main",
        desired_commit=new_commit,
        desired_tree=desired_tree,
        operation_id=operation_id,
        checkout_leases=records,
        checkout_module=checkout_module,
        protected_paths=protected,
    )
    (accelerator / "release.txt").write_text("raced\n", encoding="utf-8")
    _git(accelerator, "add", "--", "release.txt")
    _git(accelerator, "commit", "-m", "noncompliant raced accelerator")
    with pytest.raises(RuntimeError, match="changed after effect preparation"):
        program.manual_gate_authority.apply_or_rederive_gitlink_pin(
            parent=parent, intent=intent
        )
    store = _checkout_release_store(tmp_path)
    program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:03:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )

    second_id = "sha256:" + "b" * 64
    second = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=second_id,
        checkout_module=checkout_module,
    )
    missing_path = Path(str(second[0]["lock_path"]))
    missing_path.unlink()
    with pytest.raises(RuntimeError, match="disappeared before its release tombstone"):
        program.manual_gate_authority.release_checkout_leases(
            second,
            operation_id=second_id,
            release_prepared_at="2026-08-09T12:04:00+00:00",
            checkout_module=checkout_module,
            blob_store=store,
        )


def test_dqk056_rejects_externally_staged_gitlink_before_prepare(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, new_commit, protected = (
        _nested_gitlink_repositories(tmp_path)
    )
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "f" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    _git(
        parent,
        "update-index",
        "--cacheinfo",
        f"160000,{new_commit},ipfs_accelerate_py",
    )
    with pytest.raises(RuntimeError, match="externally staged"):
        program.manual_gate_authority.prepare_gitlink_pin(
            parent=parent,
            accelerator=accelerator,
            target_branch="main",
            desired_commit=new_commit,
            desired_tree=_git(accelerator, "rev-parse", "HEAD^{tree}"),
            operation_id=operation_id,
            checkout_leases=records,
            checkout_module=checkout_module,
            protected_paths=protected,
        )
    program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:04:30+00:00",
        checkout_module=checkout_module,
        blob_store=_checkout_release_store(tmp_path),
    )


def test_checkout_release_tombstone_crash_replays_exactly(
    tmp_path: Path,
) -> None:
    parent, accelerator, _old, _new, _protected = _nested_gitlink_repositories(
        tmp_path
    )
    checkout_module = program._manual_gate_checkout_module()
    operation_id = "sha256:" + "c" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    store = _checkout_release_store(tmp_path)
    crashed = False

    def crash(phase: str) -> None:
        nonlocal crashed
        if not crashed and phase.startswith("checkout_release_tombstone_persisted"):
            crashed = True
            raise RuntimeError("crash-after-release-tombstone")

    with pytest.raises(RuntimeError, match="crash-after-release-tombstone"):
        program.manual_gate_authority.release_checkout_leases(
            records,
            operation_id=operation_id,
            release_prepared_at="2026-08-09T12:05:00+00:00",
            checkout_module=checkout_module,
            blob_store=store,
            fault_injector=crash,
        )
    replayed = program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:05:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )
    assert len(replayed) == 2


def test_released_manual_lease_preserves_later_native_lock_and_strict_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, accelerator, _old, new_commit, protected = (
        _nested_gitlink_repositories(tmp_path)
    )
    released_checkout_module = program._manual_gate_checkout_module()
    monkeypatch.setattr(program, "REPO_ROOT", parent)
    monkeypatch.setattr(program, "ACCELERATE_ROOT", accelerator)
    monkeypatch.setattr(
        program,
        "_manual_gate_checkout_module",
        lambda: released_checkout_module,
    )
    checkout_module = released_checkout_module
    operation_id = "sha256:" + "e" * 64
    records = program.manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": parent, "accelerator": accelerator},
        operation_id=operation_id,
        checkout_module=checkout_module,
    )
    intent = program.manual_gate_authority.prepare_gitlink_pin(
        parent=parent,
        accelerator=accelerator,
        target_branch="main",
        desired_commit=new_commit,
        desired_tree=_git(accelerator, "rev-parse", "HEAD^{tree}"),
        operation_id=operation_id,
        checkout_leases=records,
        checkout_module=checkout_module,
        protected_paths=protected,
    )
    store = _checkout_release_store(tmp_path)
    released = list(
        program.manual_gate_authority.release_checkout_leases(
            records,
            operation_id=operation_id,
            release_prepared_at="2026-08-09T12:06:00+00:00",
            checkout_module=checkout_module,
            blob_store=store,
        )
    )
    monkeypatch.setattr(program, "_manual_gate_blob_store", lambda: store)
    journal = {
        "gate_task_id": program.RELEASE_GATE_TASK_ID,
        "lifecycle_id": operation_id,
        "checkout_lease_basis": [dict(item) for item in records],
        "checkout_leases": [dict(item) for item in records],
        "effect_intent": intent,
        "checkout_release_prepared_at": "2026-08-09T12:06:00+00:00",
        "checkout_release": released,
    }
    release_set = program._validate_manual_gate_checkout_release(journal)
    assert release_set.startswith("sha256:")

    native_path = Path(str(records[0]["lock_path"]))
    native = {
        "kind": "implementation",
        "pid": os.getpid(),
        "owner_script": "pytest",
        "repo_root": str(records[0]["repository_root"]),
        "task_id": "DQK-NATIVE",
        "attempt": 1,
        "branch": "agent/native",
        "lease_id": "native-supervisor-lease",
    }
    native_raw = (json.dumps(native, indent=2, sort_keys=True) + "\n").encode()
    native_path.write_bytes(native_raw)
    # The released native daemon creates this record with the process umask;
    # the live program's trusted common-Git ancestry and records are 0775.
    native_path.chmod(0o775)
    replayed = program.manual_gate_authority.release_checkout_leases(
        records,
        operation_id=operation_id,
        release_prepared_at="2026-08-09T12:06:00+00:00",
        checkout_module=checkout_module,
        blob_store=store,
    )
    assert list(replayed) == released
    assert native_path.read_bytes() == native_raw
    assert program._validate_manual_gate_checkout_release(journal) == release_set
    assert native_path.read_bytes() == native_raw

    duplicated = {**journal, "checkout_release": [released[0], released[0]]}
    with pytest.raises(RuntimeError, match="invalid|omits|duplicated"):
        program._validate_manual_gate_checkout_release(duplicated)


def test_signed_input_and_released_journal_forgery_fail_historical_admission(
    task_source: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_lifecycle(monkeypatch, tmp_path, task_source)
    _complete_owner(task_source, program.RELEASE_GATE_TASK_ID)
    gate = task_source.get_task(program.RELEASE_GATE_TASK_ID)
    assert gate is not None
    receipt_file = tmp_path / "forged-input.json"
    raw = json.loads(
        _signed_fixture_input(
            program.RELEASE_GATE_TASK_ID, task_source.snapshot()
        ).decode("utf-8")
    )
    raw["signature"] = "0" * 64
    receipt_file.write_text(program._canonical_json(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="signature rejected"):
        program._run_manual_gate_lifecycle(
            program.RELEASE_GATE_TASK_ID,
            receipt_file=receipt_file,
            expected_task_revision=gate.revision,
            execute_verifier=lambda *_args, **_kwargs: pytest.fail(
                "forged signed input reached verifier"
            ),
        )

    valid_file = tmp_path / "valid-input.json"
    valid_file.write_bytes(
        _signed_fixture_input(
            program.RELEASE_GATE_TASK_ID, task_source.snapshot()
        )
    )

    def execute(task_id: str, **kwargs: Any) -> dict[str, Any]:
        checked_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        return _execution_receipt(
            task_id,
            input_capture=kwargs["input_capture"],
            snapshot=kwargs["snapshot"],
            verifier_attestation=kwargs["verifier_attestation"],
            interpreter_attestation=kwargs["interpreter_attestation"],
            raw_input=kwargs["raw_input"],
            decision_preflight=kwargs["decision_preflight"],
            checked_at=checked_at,
            expires_at=checked_at + timedelta(hours=1),
        )

    program._run_manual_gate_lifecycle(
        program.RELEASE_GATE_TASK_ID,
        receipt_file=valid_file,
        expected_task_revision=gate.revision,
        execute_verifier=execute,
        relaunch_runtime=lambda *_args, **_kwargs: {"kind": "no-runnable-descendants"},
    )
    journals = sorted(
        path
        for path in program.MANUAL_GATE_LIFECYCLE_ROOT.glob("*.json")
        if path.is_file()
    )
    assert len(journals) == 1
    journal = program._read_manual_gate_journal(journals[0])
    stdout_record = journal["execution"]["process"]["stdout_blob"]
    stdout_path = program.MANUAL_GATE_LIFECYCLE_ROOT / stdout_record[
        "relative_path"
    ]
    original_stdout = stdout_path.read_bytes()
    stdout_path.write_bytes(b'{"accepted":false}')
    admitted, detail = program._manual_gate_restart_admission(task_source)
    assert not admitted
    assert "blob changed" in detail or "digest" in detail or "metadata" in detail
    stdout_path.write_bytes(original_stdout)

    journal["cas_receipt"] = {
        **journal["cas_receipt"],
        "authority_effect_id": "authority:forged",
    }
    journal["cas_receipt"]["receipt_id"] = program._manual_gate_receipt_id(
        "manual-gate-cas", journal["cas_receipt"]
    )
    program._write_manual_gate_journal(journals[0], journal)
    admitted, detail = program._manual_gate_restart_admission(task_source)
    assert not admitted
    assert (
        "authoritative CAS" in detail
        or "CAS receipt" in detail
        or "has not reached RELEASED" in detail
    )


def test_dqk081_changed_generation_binds_authoritative_materialization_and_writer(
    task_source: Any,
) -> None:
    projection = task_source.read_consistent_projection(
        ("materialization_receipts",)
    )
    rows = tuple(projection.tables["materialization_receipts"])
    assert len(rows) == 1
    source_identity = program._repository_task_source_identity(
        task_source, projection.snapshot
    )
    writer = program._repository_task_source_writer(task_source)
    output = {
        "generation_changed": True,
        "active_plan_root_cid": projection.snapshot.plan_root_cid,
        "accepted_plan_root_cid": projection.snapshot.plan_root_cid,
        "repository_tree_id": projection.snapshot.repository_tree_id,
        "generation_rollover_receipt_cid": rows[0]["receipt_cid"],
    }
    binding = program.manual_gate_authority.rollover_binding(
        output=output,
        snapshot=projection.snapshot,
        source_identity=source_identity,
        writer=writer,
        materialization_receipts=rows,
        content_identity=program._repository_content_identity,
    )
    intent = {
        "schema": "ipfs_datasets_py/duckdb-quack-manual-gate-rollover-intent@2",
        "operation_id": "sha256:" + "1" * 64,
        "execution_id": "sha256:" + "2" * 64,
        "plan_root_cid": projection.snapshot.plan_root_cid,
        "repository_tree_id": projection.snapshot.repository_tree_id,
        "generation_changed": True,
        "generation_rollover_receipt_cid": rows[0]["receipt_cid"],
    }
    intent["intent_id"] = program._manual_gate_receipt_id(
        "manual-gate-rollover-intent", intent
    )
    program._validate_manual_gate_effect_receipt(
        program.REFINEMENT_GATE_TASK_ID,
        effect_receipt=binding,
        effect_intent=intent,
        snapshot=projection.snapshot,
        materialization_receipts=rows,
        task_source_identity_id=source_identity["identity_id"],
        current_writer=writer,
    )
    # Historical admission binds the exact recorded projection while allowing
    # later task/status events to advance the current projection generation.
    advanced_snapshot = SimpleNamespace(
        plan_root_cid=projection.snapshot.plan_root_cid,
        repository_tree_id=projection.snapshot.repository_tree_id,
        projection_cid="sha256:" + "f" * 64,
        source_schema=projection.snapshot.source_schema,
        schema_version=projection.snapshot.schema_version,
    )
    program._validate_manual_gate_effect_receipt(
        program.REFINEMENT_GATE_TASK_ID,
        effect_receipt=binding,
        effect_intent=intent,
        snapshot=advanced_snapshot,
        materialization_receipts=rows,
        task_source_identity_id=source_identity["identity_id"],
        current_writer=writer,
    )
    assert binding["materialization_receipt"]["receipt_cid"] == rows[0][
        "receipt_cid"
    ]
    assert binding["writer"] == {
        "writer_id": writer[0],
        "fencing_token": writer[1],
    }
    forged = {**output, "generation_rollover_receipt_cid": "cid:forged"}
    with pytest.raises(RuntimeError, match="not authoritative"):
        program.manual_gate_authority.rollover_binding(
            output=forged,
            snapshot=projection.snapshot,
            source_identity=source_identity,
            writer=writer,
            materialization_receipts=rows,
            content_identity=program._repository_content_identity,
        )

    TaskSourceIdentity, _Evidence, _Daemon = program._repository_authority_types()
    foreign_identity_input = dict(source_identity)
    foreign_identity_input.pop("identity_id")
    foreign_identity_input["source_id"] = "projection:foreign"
    foreign_identity = TaskSourceIdentity.from_dict(foreign_identity_input).to_dict()
    foreign_source = {**binding, "task_source_identity": foreign_identity}
    foreign_source.pop("binding_id")
    foreign_source["binding_id"] = program.manual_gate_authority.content_id(
        "manual-gate-rollover-binding", foreign_source
    )
    with pytest.raises(RuntimeError, match="task-source identity"):
        program._validate_manual_gate_effect_receipt(
            program.REFINEMENT_GATE_TASK_ID,
            effect_receipt=foreign_source,
            effect_intent=intent,
            snapshot=projection.snapshot,
            materialization_receipts=rows,
            task_source_identity_id=source_identity["identity_id"],
            current_writer=writer,
        )

    foreign_writer = {
        **binding,
        "writer": {"writer_id": "forged", "fencing_token": writer[1]},
    }
    foreign_writer.pop("binding_id")
    foreign_writer["binding_id"] = program.manual_gate_authority.content_id(
        "manual-gate-rollover-binding", foreign_writer
    )
    with pytest.raises(RuntimeError, match="writer fence"):
        program._validate_manual_gate_effect_receipt(
            program.REFINEMENT_GATE_TASK_ID,
            effect_receipt=foreign_writer,
            effect_intent=intent,
            snapshot=projection.snapshot,
            materialization_receipts=rows,
            task_source_identity_id=source_identity["identity_id"],
            current_writer=writer,
        )

    with pytest.raises(RuntimeError, match="not in DuckDB authority"):
        program._validate_manual_gate_effect_receipt(
            program.REFINEMENT_GATE_TASK_ID,
            effect_receipt=binding,
            effect_intent=intent,
            snapshot=projection.snapshot,
            materialization_receipts=(),
            task_source_identity_id=source_identity["identity_id"],
            current_writer=writer,
        )
    with pytest.raises(RuntimeError, match="requires a writer fence"):
        program.manual_gate_authority.rollover_binding(
            output=output,
            snapshot=projection.snapshot,
            source_identity=source_identity,
            writer=None,
            materialization_receipts=rows,
            content_identity=program._repository_content_identity,
        )

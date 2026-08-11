from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

pytest.importorskip("duckdb")

from scripts.ops import ipfs_datasets_duckdb_quack_program as program


REAL_VERIFY_PARENT_RETRY_RESET_ANCHOR = program._verify_parent_retry_reset_anchor
from ipfs_accelerate_py.agent_supervisor.authorization_logic import (
    ControlMutationPolicy,
)
from ipfs_accelerate_py.agent_supervisor.checkout_lock import (
    checkout_mutation_lock_path,
    checkout_repository_id,
)
from ipfs_accelerate_py.agent_supervisor.control_contracts import (
    AuthorizationDecision,
    AuthorizationVerdict,
    IdempotencyKey,
    Operation,
    OperationAuthority,
    OperationRequest,
)
from ipfs_accelerate_py.agent_supervisor.duckdb_retry_reset import (
    RETRY_RESET_GRANT,
    RETRY_RESET_OWNER_FILE,
    RETRY_RESET_POLICY_SCHEMA,
    LaneBinding,
    RetryResetOwnerConfig,
    inspect_incomplete_retry_resets,
    prepare_duckdb_retry_reset_execution_intent,
    retry_reset_expected_effect,
)
from ipfs_accelerate_py.agent_supervisor.duckdb_task_source import DuckDBTaskSource
from ipfs_accelerate_py.agent_supervisor.formal_verification_contracts import (
    content_identity,
)


class InjectedCrash(RuntimeError):
    pass


@dataclass(frozen=True)
class FakeLane:
    state_prefix: str
    state_path: str
    queue_path: str

    @property
    def supervisor_pid_path(self) -> str:
        return str(
            Path(self.state_path).with_name(f"{self.state_prefix}_supervisor.pid")
        )

    @property
    def daemon_pid_path(self) -> str:
        return str(
            Path(self.state_path).with_name(f"{self.state_prefix}_managed_daemon.pid")
        )

    @property
    def status_path(self) -> str:
        return str(
            Path(self.state_path).with_name(
                f"{self.state_prefix}_supervisor_status.json"
            )
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "state_prefix": self.state_prefix,
            "state_path": self.state_path,
            "queue_path": self.queue_path,
            "supervisor_pid_path": self.supervisor_pid_path,
            "daemon_pid_path": self.daemon_pid_path,
            "status_path": self.status_path,
        }


class FakeRequest:
    request_id = "request:retry:dqk-001"
    authorization = SimpleNamespace(
        decision_id="decision:retry:dqk-001",
        evaluated_at_ms=1_000,
        expires_at_ms=None,
    )
    lease_id = "lease:retry:dqk-001"
    fencing_epoch = 7

    def canonical_bytes(self) -> bytes:
        return b'{"request":"retry:dqk-001"}'


def _command(token: str) -> list[str]:
    return [
        "/sealed/python",
        "-m",
        "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner",
        "--duration-seconds",
        "inf",
        "--stamp",
        f"dqk-fixture-{token}",
        "--implementation-supervisor-lanes-per-track",
        "2",
        "--common-arg=--execution-slice-task-id",
        "--common-arg=DQK-001",
    ]


def _git_at(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _retry_policy_payload(policy: ControlMutationPolicy) -> dict[str, Any]:
    return {
        "schema": RETRY_RESET_POLICY_SCHEMA,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "permits": [item.to_record() for item in policy.permits],
        "current_tree_ids": dict(policy.current_tree_ids),
        "current_objective_revisions": dict(
            policy.current_objective_revisions
        ),
        "active_lease_fences": dict(policy.active_lease_fences),
    }


@pytest.fixture()
def real_execution_intent_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    """Build a canonical released reset authority without touching live state."""

    repository = (tmp_path / "repository").resolve()
    repository.mkdir()
    _git_at(repository, "init", "-q")
    _git_at(repository, "config", "user.name", "Retry Boundary Test")
    _git_at(
        repository,
        "config",
        "user.email",
        "retry-boundary@example.invalid",
    )
    _git_at(repository, "checkout", "-q", "-b", program.TARGET_BRANCH)

    accelerator_source = (tmp_path / "accelerator-source").resolve()
    accelerator_source.mkdir()
    _git_at(accelerator_source, "init", "-q")
    _git_at(accelerator_source, "config", "user.name", "Retry Boundary Test")
    _git_at(
        accelerator_source,
        "config",
        "user.email",
        "retry-boundary@example.invalid",
    )
    (accelerator_source / "bridge.txt").write_text(
        "pinned accelerator generation\n", encoding="utf-8"
    )
    _git_at(accelerator_source, "add", "bridge.txt")
    _git_at(accelerator_source, "commit", "-q", "-m", "pin accelerator")
    _git_at(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(accelerator_source),
        "ipfs_accelerate_py",
    )
    (repository / "plan-root.txt").write_text(
        "admitted retry boundary\n", encoding="utf-8"
    )
    _git_at(repository, "add", ".gitmodules", "ipfs_accelerate_py", "plan-root.txt")
    _git_at(repository, "commit", "-q", "-m", "admit retry boundary")

    runtime = (tmp_path / "runtime").resolve()
    runtime.mkdir()
    database_path = runtime / "control.duckdb"
    master_root = runtime / "master"
    master_pid_path = master_root / "supervisor.pid"
    master_identity_path = master_root / "supervisor.identity.json"
    master_log_path = master_root / "supervisor.log"
    accelerator = (repository / "ipfs_accelerate_py").resolve()
    monkeypatch.setattr(program, "REPO_ROOT", repository)
    monkeypatch.setattr(program, "ACCELERATE_ROOT", accelerator)
    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "DATABASE_PATH", database_path)
    monkeypatch.setattr(program, "STATE_ROOT", runtime / "state")
    monkeypatch.setattr(program, "MASTER_ROOT", master_root)
    monkeypatch.setattr(program, "MASTER_PID", master_pid_path)
    monkeypatch.setattr(program, "MASTER_IDENTITY", master_identity_path)
    monkeypatch.setattr(program, "MASTER_LOG", master_log_path)
    monkeypatch.setattr(
        program,
        "_accelerate_module",
        lambda _canonical_name, legacy_name: importlib.import_module(legacy_name),
    )
    monkeypatch.setattr(
        program, "MANUAL_GATE_LIFECYCLE_ROOT", runtime / "manual-gates"
    )
    monkeypatch.setattr(
        program,
        "MANUAL_GATE_LIFECYCLE_LOCK",
        runtime / "manual-gates/.lifecycle.lock",
    )

    repository_head_commit = _git_at(repository, "rev-parse", "HEAD")
    repository_head_tree = _git_at(repository, "rev-parse", "HEAD^{tree}")
    task_source_repository_tree_id = program._repository_tree_id()
    source = DuckDBTaskSource(database_path)
    source.materialize(
        program.formal_source(task_source_repository_tree_id),
        repository_tree_id=task_source_repository_tree_id,
        expected_absent=True,
    )
    task = source.get_task("DQK-007")
    assert task is not None
    writer = source.current_writer_fence()
    lane = LaneBinding(
        "dqk",
        "state/lane-0/dqk_task_state.json",
        "state/lane-0/task_queue.json",
    )
    parameters = {
        "task_source_kind": "duckdb",
        "database_path": "control.duckdb",
        "plan_root_cid": source.snapshot().plan_root_cid,
        "task_source_repository_tree_id": task_source_repository_tree_id,
        "repository_head_commit": repository_head_commit,
        "task_cid": task.task_cid,
        "task_alias": task.task_alias,
        "task_revision": task.revision,
        "expected_status": task.status,
        "reopen_status": "retrying",
        "writer_id": writer.writer_id,
        "writer_fencing_token": writer.fencing_token,
        "lanes": [
            {
                "state_prefix": lane.state_prefix,
                "state_path": lane.state_path,
                "queue_path": lane.queue_path,
            }
        ],
        "lifecycle_owner_paths": ["master/supervisor.pid"],
    }
    repository_id = checkout_repository_id(repository)
    expected_effect = retry_reset_expected_effect(
        repository_root=str(repository),
        state_root=str(runtime),
        repository_id=repository_id,
        tree_id=repository_head_tree,
        parameters=parameters,
    )
    now_ms = time.time_ns() // 1_000_000
    common = {
        "operation": Operation.RETRY,
        "repository_root": str(repository),
        "state_root": str(runtime),
        "repository_id": repository_id,
        "tree_id": repository_head_tree,
        "objective_id": "goal:duckdb-quack-retry-boundary",
        "objective_revision": "goal-revision:1",
        "policy_id": "policy:duckdb-quack-retry-boundary",
        "policy_revision": "policy-revision:1",
        "caller": "operator:retry-boundary-test",
    }
    decision = AuthorizationDecision(
        verdict=AuthorizationVerdict.PERMIT,
        granted_authority=OperationAuthority.MUTATION,
        authorized_effect_ids=(expected_effect.effect_id,),
        grant_ids=(RETRY_RESET_GRANT, f"grant:duckdb-writer:{writer.writer_id}"),
        lease_id="lease:retry-boundary-test",
        fencing_epoch=writer.fencing_token,
        evaluated_at_ms=now_ms - 60_000,
        expires_at_ms=now_ms + 600_000,
        **common,
    )
    request = OperationRequest(
        expected_effects=(expected_effect,),
        parameters=parameters,
        idempotency=IdempotencyKey(
            key=f"retry-boundary:{task.task_cid}:revision-{task.revision}",
            operation=Operation.RETRY,
            caller=common["caller"],
            repository_id=repository_id,
            objective_id=common["objective_id"],
        ),
        authorization=decision,
        lease_id=decision.lease_id,
        fencing_epoch=decision.fencing_epoch,
        **common,
    )
    policy = ControlMutationPolicy(
        policy_id=common["policy_id"],
        policy_revision=common["policy_revision"],
        permits=(decision,),
        current_tree_ids={repository_id: repository_head_tree},
        current_objective_revisions={
            common["objective_id"]: common["objective_revision"]
        },
        active_lease_fences={decision.lease_id: decision.fencing_epoch},
    )
    policy_path = runtime / "control/retry-reset-policy.json"
    policy_path.parent.mkdir()
    policy_bytes = (
        json.dumps(_retry_policy_payload(policy), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    policy_path.write_bytes(policy_bytes)
    owner = RetryResetOwnerConfig(
        repository_root=str(repository),
        repository_id=repository_id,
        database_path="control.duckdb",
        task_source_repository_tree_id=task_source_repository_tree_id,
        policy_path=policy_path.relative_to(runtime).as_posix(),
        policy_digest="sha256:" + hashlib.sha256(policy_bytes).hexdigest(),
        lanes=(lane,),
        lifecycle_owner_paths=("master/supervisor.pid",),
    )
    owner_path = runtime / RETRY_RESET_OWNER_FILE
    owner_path.write_text(
        json.dumps(owner.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    owner_path.chmod(0o600)
    owner_digest = "sha256:" + hashlib.sha256(owner_path.read_bytes()).hexdigest()

    accelerator_head = _git_at(accelerator, "rev-parse", "HEAD")
    checkout_binding = []
    for role, checkout in (("parent", repository), ("accelerator", accelerator)):
        lock_path = Path(checkout_mutation_lock_path(checkout))
        checkout_binding.append(
            {
                "role": role,
                "repository_root": str(checkout),
                "repository_id": checkout_repository_id(checkout),
                "lock_path": str(lock_path.parent.resolve() / lock_path.name),
                "branch": _git_at(checkout, "branch", "--show-current"),
                "head_commit": _git_at(checkout, "rev-parse", "HEAD"),
                "head_tree": _git_at(checkout, "rev-parse", "HEAD^{tree}"),
                "parent_accelerator_gitlink": accelerator_head,
            }
        )
    checkout_binding.sort(key=lambda item: item["lock_path"])

    digest = "sha256:" + "a" * 64
    environment_root = (runtime / "environment").resolve()
    environment_receipt_path = runtime / "environment-receipt.json"
    environment_evidence = {
        "receipt_path": str(environment_receipt_path.resolve()),
        "receipt_sha256": "",
        "receipt_id": "environment:retry-boundary-test",
        "environment_root": str(environment_root),
        "sealed_python_launcher_path": str(
            (environment_root / "bin/dqk-sealed-python").resolve()
        ),
        "sealed_python_launcher_sha256": digest,
        "base_python_sha256": digest,
        "site_packages_manifest_sha256": digest,
        "duckdb_version": "1.5.5",
        "duckdb_record_evidence_sha256": digest,
    }
    environment_receipt_path.write_text(
        json.dumps(
            {
                "receipt_id": environment_evidence["receipt_id"],
                "probe": {
                    key: value
                    for key, value in environment_evidence.items()
                    if key
                    not in {"receipt_path", "receipt_sha256", "receipt_id"}
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    environment_evidence["receipt_sha256"] = "sha256:" + hashlib.sha256(
        environment_receipt_path.read_bytes()
    ).hexdigest()

    master = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(120)",
            "--duration-seconds",
            "3600",
            "--implementation-supervisor-lanes-per-track",
            "1",
            "--common-arg=--execution-slice-task-id",
            "--common-arg=DQK-007",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def stop_master() -> None:
        if master.poll() is not None:
            return
        master.terminate()
        try:
            master.wait(timeout=5)
        except subprocess.TimeoutExpired:
            master.kill()
            master.wait(timeout=5)

    try:
        deadline = time.monotonic() + 5
        actual_master = None
        while time.monotonic() < deadline:
            actual_master = program._process_birth_identity(master.pid)
            if actual_master and actual_master.get("argv"):
                break
            time.sleep(0.01)
        assert actual_master is not None
        assert os.getsid(master.pid) == master.pid
        stored_master = {
            "schema": "ipfs_datasets_py/duckdb-quack-master-identity@3",
            "program_id": program.PROGRAM_ID,
            "repository_root": str(repository),
            "master_root": str(master_root.resolve()),
            "master_pid_path": str(master_pid_path.resolve()),
            "plan_root_cid": source.snapshot().plan_root_cid,
            "repository_tree_id": task_source_repository_tree_id,
            "execution_slice_sha256": digest,
            "execution_slice_task_count": 1,
            "authorization_held_set_sha256": digest,
            "authorization_held_task_count": 0,
            "bootstrap_completion_evidence_id": "",
            "lane_count": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "python_environment_sha256": digest,
            **{
                key: actual_master[key]
                for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
            },
        }
        released_reset_module = program._retry_reset_module()
        request_file_bytes = request.canonical_bytes()
        context = {
            "module": released_reset_module,
            "request": request,
            "request_file_bytes": request_file_bytes,
            "request_file_digest": "sha256:"
            + hashlib.sha256(request_file_bytes).hexdigest(),
            "binding": released_reset_module._binding_from_parameters(parameters),
            "owner": owner,
            "owner_digest": owner_digest,
            "policy": policy,
            "policy_path": policy_path.resolve(),
            "snapshot": source.snapshot(),
            "task": task,
            "writer": writer,
            "stored_master": stored_master,
            "actual_master": actual_master,
            "lane_count": 1,
            "head_commit": repository_head_commit,
            "head_tree": repository_head_tree,
            "checkout_binding": checkout_binding,
            "environment_evidence": environment_evidence,
        }
        parent_prepared = program._new_retry_lifecycle_journal(context)
        parent_path = program._retry_lifecycle_journal_path(request)
        monkeypatch.setattr(program, "_source", lambda require=True: source)
        monkeypatch.setattr(
            program,
            "_accelerate_imports",
            lambda: (DuckDBTaskSource, (lambda: False, lambda: False)),
        )
        monkeypatch.setattr(
            program,
            "_external_dqp_status",
            lambda: {
                "master_alive": True,
                "lane_count": 4,
                "expected_lane_count": 4,
                "stale_or_unbound_lanes": [],
                "completed_count": 0,
                "task_count": 39,
                "release_status": "pending",
            },
        )
        yield {
            "runtime": runtime,
            "source": source,
            "request": request,
            "policy": policy,
            "owner": owner,
            "request_file_bytes": request_file_bytes,
            "parent_prepared": parent_prepared,
            "parent_path": parent_path,
            "master": master,
            "stop_master": stop_master,
        }
    finally:
        stop_master()


@pytest.fixture()
def lifecycle_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    runtime = (tmp_path / "runtime").resolve()
    runtime.mkdir()
    master = runtime / "master"
    master.mkdir()
    request_file = tmp_path / "request.json"
    request_file.write_text("{}\n", encoding="utf-8")
    accelerator = (tmp_path / "accelerator").resolve()
    accelerator.mkdir()
    parent_common = (tmp_path / "parent-common-git").resolve()
    accelerator_common = (tmp_path / "accelerator-common-git").resolve()
    parent_common.mkdir(mode=0o700)
    accelerator_common.mkdir(mode=0o700)

    def checkout_lock_path(root: Path) -> Path:
        common = parent_common if root.resolve() == tmp_path.resolve() else accelerator_common
        return common / "implementation-main-merge.lock"

    def checkout_repository_id(root: Path) -> str:
        role = "parent" if root.resolve() == tmp_path.resolve() else "accelerator"
        return f"repository:test:{role}"

    real_checkout_module = program._retry_checkout_module()
    checkout_module = SimpleNamespace(
        checkout_mutation_lock_path=checkout_lock_path,
        checkout_repository_id=checkout_repository_id,
        serialized_lock_update=real_checkout_module.serialized_lock_update,
    )
    checkout_binding = sorted(
        [
            {
                "role": "parent",
                "repository_root": str(tmp_path.resolve()),
                "repository_id": checkout_repository_id(tmp_path),
                "lock_path": str(checkout_lock_path(tmp_path)),
                "branch": program.TARGET_BRANCH,
                "head_commit": "a" * 40,
                "head_tree": "b" * 40,
                "parent_accelerator_gitlink": "c" * 40,
            },
            {
                "role": "accelerator",
                "repository_root": str(accelerator),
                "repository_id": checkout_repository_id(accelerator),
                "lock_path": str(checkout_lock_path(accelerator)),
                "branch": "feat/test-accelerator",
                "head_commit": "c" * 40,
                "head_tree": "d" * 40,
                "parent_accelerator_gitlink": "c" * 40,
            },
        ],
        key=lambda item: item["lock_path"],
    )
    lanes = tuple(
        FakeLane(
            "dqk",
            f"state/lane-{index}/dqk_task_state.json",
            f"state/lane-{index}/task_queue.json",
        )
        for index in range(2)
    )
    old_master = {
        "pid": 501,
        "boot_id": "boot:test",
        "start_ticks": 100,
        "cmdline_sha256": "sha256:" + "1" * 64,
        "argv": _command("0" * 32),
    }
    owner_identity = {
        "pid": 900,
        "boot_id": "boot:test",
        "start_ticks": 200,
        "cmdline_sha256": "sha256:" + "2" * 64,
        "argv": ["python", "recover-task"],
    }
    request = FakeRequest()
    request.authorization = SimpleNamespace(
        decision_id="decision:retry:dqk-001",
        evaluated_at_ms=1_000,
        expires_at_ms=9_999_999_999_999,
    )
    request.repository_root = str(tmp_path.resolve())
    request.state_root = str(runtime)
    request.tree_id = "b" * 40
    request.parameters = {
        "task_source_kind": "duckdb",
        "database_path": "control.duckdb",
        "plan_root_cid": "plan:cid:dqk",
        "task_source_repository_tree_id": "repository:tree:dqk",
        "repository_head_commit": "a" * 40,
        "task_cid": "task:cid:dqk-001",
        "task_alias": "DQK-001",
        "task_revision": 4,
        "expected_status": "failed",
        "reopen_status": "retrying",
        "writer_id": "writer:dqk",
        "writer_fencing_token": 7,
        "lanes": [
            {
                "state_prefix": lane.state_prefix,
                "state_path": lane.state_path,
                "queue_path": lane.queue_path,
            }
            for lane in lanes
        ],
        "lifecycle_owner_paths": ["master/supervisor.pid"],
    }
    binding = SimpleNamespace(
        task_cid="task:cid:dqk-001",
        task_alias="DQK-001",
        task_revision=4,
        expected_status="failed",
        writer_id="writer:dqk",
        writer_fencing_token=7,
        lanes=lanes,
        lifecycle_owner_paths=("master/supervisor.pid",),
    )
    owner = SimpleNamespace(
        policy_digest="sha256:" + "3" * 64,
        to_dict=lambda: {
            "schema": "owner@1",
            "lanes": [lane.to_dict() for lane in lanes],
        },
    )
    context = {
        "module": SimpleNamespace(
            RETRY_RESET_OWNER_FILE="duckdb-retry-reset-owner.json"
        ),
        "request": request,
        "request_file_bytes": b"{}\n",
        "request_file_digest": "sha256:" + hashlib.sha256(b"{}\n").hexdigest(),
        "binding": binding,
        "owner": owner,
        "owner_digest": "sha256:" + "4" * 64,
        "policy": SimpleNamespace(
            policy_id="policy:dqk",
            policy_revision="revision:1",
        ),
        "policy_path": runtime / "control/retry-policy.json",
        "snapshot": SimpleNamespace(
            plan_root_cid="plan:cid:dqk",
            repository_tree_id="repository:tree:dqk",
        ),
        "task": SimpleNamespace(
            task_cid=binding.task_cid,
            task_alias=binding.task_alias,
            status=binding.expected_status,
            revision=binding.task_revision,
        ),
        "writer": SimpleNamespace(writer_id="writer:dqk", fencing_token=7),
        "stored_master": {"schema": "master@2", "lane_count": 2, **old_master},
        "actual_master": old_master,
        "lane_count": 2,
        "head_commit": "a" * 40,
        "head_tree": "b" * 40,
        "checkout_binding": checkout_binding,
        "environment_evidence": {
            "receipt_id": "receipt:environment",
            "sealed_python_launcher_sha256": "sha256:" + "6" * 64,
        },
    }
    released_reset_module = program._retry_reset_module()
    # The fixture deliberately points ACCELERATE_ROOT at an isolated checkout
    # model below.  Preserve the already-origin-checked released module so new
    # parent binding validation does not try to import authority code from that
    # synthetic checkout.
    monkeypatch.setattr(
        program, "_retry_reset_module", lambda: released_reset_module
    )

    def imported(canonical_name: str, legacy_name: str) -> Any:
        if canonical_name.endswith(".duckdb_retry_reset"):
            # This unit fixture models the parent retry lifecycle only.  The
            # released reset journal, owner configuration, and DuckDB event
            # source are covered by the integration harness below; reporting
            # no released-reset journals here lets inspection reach the
            # synthetic parent lifecycle evidence under RUNTIME_ROOT.
            return SimpleNamespace(inspect_incomplete_retry_resets=lambda _root: ())
        return importlib.import_module(legacy_name)

    monkeypatch.setattr(program, "_accelerate_module", imported)
    prepared_intent: dict[str, Any] = {}

    def recover_execution_intent(*_args: Any, **_kwargs: Any) -> Any:
        projection = prepared_intent.get("projection")
        return copy.deepcopy(projection) if projection is not None else None

    def prepare_execution_intent(
        _request: Any,
        *,
        parent_prepared: dict[str, Any],
        parent_journal_path: Path,
        fault_injector: Any | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        existing = prepared_intent.get("projection")
        if existing is not None:
            if existing["parent_prepared"] != parent_prepared:
                raise released_reset_module.DuckDBRetryResetConflict(
                    "conflicting parent"
                )
            return copy.deepcopy(existing)
        intent_cid = content_identity(
            {"namespace": "fixture-retry-execution-intent", **parent_prepared}
        )
        event_cid = content_identity(
            {"namespace": "fixture-retry-execution-event", "cid": intent_cid}
        )
        projection = {
            "parent_prepared": copy.deepcopy(parent_prepared),
            "parent_journal_path": str(parent_journal_path),
            "request": {
                "digest": program._retry_lifecycle_request_digest(request)
            },
            "execution_intent_cid": intent_cid,
            "projection_path": str(
                runtime
                / "duckdb-retry-reset/execution-intents"
                / f"{intent_cid}.json"
            ),
            "preparation_event": {
                "event_cid": event_cid,
                "sequence": 1,
                "revision": 1,
            },
        }
        prepared_intent["projection"] = copy.deepcopy(projection)
        if fault_injector:
            fault_injector("execution_intent_event_appended")
            fault_injector("execution_intent_projection_written")
        return projection

    context["module"] = SimpleNamespace(
        RETRY_RESET_OWNER_FILE=released_reset_module.RETRY_RESET_OWNER_FILE,
        RETRY_RESET_EXECUTION_INTENT_BINDING_SCHEMA=(
            released_reset_module.RETRY_RESET_EXECUTION_INTENT_BINDING_SCHEMA
        ),
        RETRY_RESET_RECEIPT_SCHEMA=released_reset_module.RETRY_RESET_RECEIPT_SCHEMA,
        DuckDBRetryResetConflict=released_reset_module.DuckDBRetryResetConflict,
        recover_duckdb_retry_reset_execution_intent=recover_execution_intent,
        prepare_duckdb_retry_reset_execution_intent=prepare_execution_intent,
        retry_reset_execution_intent_binding=(
            released_reset_module.retry_reset_execution_intent_binding
        ),
    )
    state = {
        "master_live": True,
        "reset_invocations": 0,
        "reset_effects": set(),
        "relaunch_invocations": 0,
        "relaunch_effects": set(),
        "checkout_binding": checkout_binding,
        "current_owner": owner_identity,
        "live_owner_pids": set(),
    }

    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "DATABASE_PATH", runtime / "control.duckdb")
    monkeypatch.setattr(program, "STATE_ROOT", runtime / "state")
    monkeypatch.setattr(program, "MASTER_ROOT", master)
    monkeypatch.setattr(program, "MASTER_PID", master / "supervisor.pid")
    monkeypatch.setattr(program, "MASTER_IDENTITY", master / "supervisor.identity.json")
    monkeypatch.setattr(program, "MASTER_LOG", master / "supervisor.log")
    monkeypatch.setattr(program, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(program, "ACCELERATE_ROOT", accelerator)
    monkeypatch.setattr(program, "_retry_checkout_module", lambda: checkout_module)
    monkeypatch.setattr(
        program,
        "_retry_checkout_snapshot",
        lambda: [dict(item) for item in state["checkout_binding"]],
    )
    def lifecycle_authority(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("require_fresh_permit"):
            expires_at_ms = request.authorization.expires_at_ms
            now_ms = program.time.time_ns() // 1_000_000
            if expires_at_ms is None or now_ms >= expires_at_ms:
                raise RuntimeError("retry permit is not fresh")
        return context

    monkeypatch.setattr(program, "_retry_lifecycle_authority", lifecycle_authority)
    monkeypatch.setattr(
        program,
        "_decode_retry_lifecycle_request_file",
        lambda _path: (request, b"{}\n"),
    )
    monkeypatch.setattr(
        program,
        "_current_owner_identity",
        lambda: dict(state["current_owner"]),
    )
    monkeypatch.setattr(
        program,
        "_capture_process_tree",
        lambda _pid: (dict(old_master),),
    )
    monkeypatch.setattr(program, "_process_session_id", lambda pid: 501 if pid == 501 else None)
    monkeypatch.setattr(program, "_process_session_members", lambda _session_id: ())
    monkeypatch.setattr(
        program,
        "_declared_retry_owner_pids",
        lambda _context: {"master/supervisor.pid": (501,)},
    )
    monkeypatch.setattr(
        program,
        "_identity_is_live",
        lambda identity: bool(
            state["master_live"]
            if identity.get("pid") == 501
            else identity.get("pid") in state["live_owner_pids"]
        ),
    )
    monkeypatch.setattr(
        program,
        "_process_birth_identity",
        lambda pid: dict(old_master) if pid == 501 and state["master_live"] else None,
    )
    monkeypatch.setattr(program, "_assert_retry_runtime_quiescent", lambda *_args: None)

    def fake_kill(pid: int, signum: int) -> None:
        assert pid == 501
        assert signum == program.signal.SIGTERM
        state["master_live"] = False

    monkeypatch.setattr(program.os, "kill", fake_kill)

    def reset_receipt() -> dict[str, Any]:
        projection = prepared_intent.get("projection") or {}
        material = {
            "schema": (
                "ipfs_accelerate_py/agent-supervisor/duckdb-retry-reset-receipt@1"
            ),
            "request_id": request.request_id,
            "task_cid": binding.task_cid,
            "task_alias": binding.task_alias,
            "writer_id": binding.writer_id,
            "writer_fencing_token": binding.writer_fencing_token,
            "execution_intent_cid": projection.get("execution_intent_cid"),
        }
        return {**material, "receipt_cid": content_identity(material)}

    def reset_anchor(receipt: dict[str, Any]) -> dict[str, Any]:
        anchor = {
            "schema": program.RETRY_RESET_ANCHOR_SCHEMA,
            "journal_path": str(runtime / "duckdb-retry-reset/journals/reset.json"),
            "journal_key_cid": "reset",
            "request_id": request.request_id,
            "intent_cid": "intent:retry-reset",
            "receipt_cid": receipt["receipt_cid"],
            "completion_event": {
                "event_cid": receipt["receipt_cid"],
                "sequence": 2,
                "revision": 5,
            },
        }
        return {**anchor, "anchor_cid": program._retry_reset_anchor_cid(anchor)}

    def reset_once(
        _context: Any,
        _journal: Mapping[str, Any],
        *,
        path: Path,
    ) -> dict[str, Any]:
        assert path == program._retry_lifecycle_journal_path(request)
        state["reset_invocations"] += 1
        state["reset_effects"].add(request.request_id)
        return reset_receipt()

    monkeypatch.setattr(program, "_execute_retry_reset_once", reset_once)
    monkeypatch.setattr(
        program,
        "_completed_retry_reset_evidence",
        lambda _context: (
            (reset_receipt(), reset_anchor(reset_receipt()))
            if state["reset_effects"]
            else None
        ),
    )
    monkeypatch.setattr(
        program,
        "_verify_parent_retry_reset_anchor",
        lambda journal, **_kwargs: (
            reset_receipt()
            if journal.get("retry_reset_anchor") == reset_anchor(reset_receipt())
            else (_ for _ in ()).throw(RuntimeError("reset anchor mismatch"))
        ),
    )
    monkeypatch.setattr(
        program,
        "supervisor_command",
        lambda *, launch_token, **_kwargs: _command(launch_token),
    )
    monkeypatch.setattr(
        program,
        "_launch_marker",
        lambda: {
            "boot_id": "boot:test",
            "start_ticks_floor": 300,
            "wall_time_ns": 1,
            "pidfile_before": None,
        },
    )

    def relaunch_once(_context: Any, journal: dict[str, Any]) -> dict[str, Any]:
        state["relaunch_invocations"] += 1
        token = journal["relaunch"]["launch_token"]
        state["relaunch_effects"].add(token)
        return {
            "pid": 777,
            "boot_id": "boot:test",
            "start_ticks": 400,
            "cmdline_sha256": "sha256:" + "5" * 64,
            "argv": journal["relaunch"]["command"],
        }

    monkeypatch.setattr(program, "_launch_or_adopt_retry_master", relaunch_once)
    monkeypatch.setattr(
        program, "_master_process_status", lambda *_args, **_kwargs: (True, "bound")
    )
    monkeypatch.setattr(program, "_read_master_identity", lambda: {"lane_count": 2})
    return {
        "request_file": request_file,
        "context": context,
        "state": state,
    }


@pytest.mark.parametrize(
    "crash_phase",
    (
        "prepared",
        "draining",
        "drain_signalled",
        "drained",
        "reset_executed",
        "reset_committed",
        "relaunching",
        "relaunch_bound",
        "completed",
    ),
)
def test_retry_lifecycle_replays_each_boundary_without_duplicate_effects(
    lifecycle_harness: dict[str, Any],
    crash_phase: str,
) -> None:
    tripped = False

    def inject(phase: str) -> None:
        nonlocal tripped
        if not tripped and phase == crash_phase:
            tripped = True
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=inject,
        )

    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    replay = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    state = lifecycle_harness["state"]

    assert replay == receipt
    assert receipt["schema"] == program.RETRY_LIFECYCLE_RECEIPT_SCHEMA
    assert state["reset_effects"] == {FakeRequest.request_id}
    assert len(state["relaunch_effects"]) == 1


def test_incomplete_parent_lifecycle_journal_blocks_existing_inspection(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_after_prepare(phase: str) -> None:
        if phase == "prepared":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_after_prepare,
        )

    inspection = program._retry_reset_inspection()

    assert not inspection["ok"]
    assert inspection["incomplete"][0]["kind"] == "retry_lifecycle"
    assert inspection["incomplete"][0]["phase"] == "prepared"


def test_retry_commands_require_an_explicit_request_file() -> None:
    preview = program.build_parser().parse_args(
        ["retry-preview", "--request-file", "request.json"]
    )
    recover = program.build_parser().parse_args(
        ["recover-task", "--request-file", "request.json"]
    )

    assert preview.handler is program.cmd_retry_preview
    assert recover.handler is program.cmd_recover_task
    assert recover.drain_timeout_seconds == 90.0


def test_relaunch_journal_cannot_authorize_a_forged_command(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_before_launch(phase: str) -> None:
        if phase == "relaunching":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_before_launch,
        )
    request = lifecycle_harness["context"]["request"]
    journal_path = program._retry_lifecycle_journal_path(request)
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    payload["relaunch"]["command"].append("--forged-option")
    # Even a rewritten phase digest cannot turn non-canonical argv into an
    # executable lifecycle transition; the owner reconstructs it independently.
    payload["relaunch_intent_cid"] = program._retry_lifecycle_relaunch_intent_cid(
        payload
    )
    journal_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="not the canonical sealed command"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
        )


def test_retry_lifecycle_lock_rejects_a_symlink(
    lifecycle_harness: dict[str, Any],
) -> None:
    _journal_root, lock_path = program._retry_lifecycle_paths()
    target = lock_path.with_name("foreign.lock")
    target.write_text("foreign\n", encoding="utf-8")
    lock_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="lock is unavailable"):
        with program._retry_lifecycle_lock_context():
            pytest.fail("symlinked lifecycle lock was admitted")


def test_retry_authority_rejects_state_root_in_place_of_runtime_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = (tmp_path / "runtime").resolve()
    state = runtime / "state"
    repository = (tmp_path / "repository").resolve()
    runtime.mkdir()
    state.mkdir()
    repository.mkdir()
    request_path = tmp_path / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    request = SimpleNamespace(
        operation=SimpleNamespace(value="retry"),
        dry_run=False,
        repository_root=str(repository),
        state_root=str(state),
    )
    control = SimpleNamespace(decode_operation_request=lambda _payload: request)

    def imported(canonical: str, _legacy: str) -> Any:
        if canonical.endswith("control_contracts"):
            return control
        return SimpleNamespace()

    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "STATE_ROOT", state)
    monkeypatch.setattr(program, "REPO_ROOT", repository)
    monkeypatch.setattr(program, "_retry_reset_module", lambda: SimpleNamespace())
    monkeypatch.setattr(program, "_accelerate_module", imported)

    with pytest.raises(RuntimeError, match="complete RUNTIME_ROOT"):
        program._retry_lifecycle_authority(
            request_path,
            require_original_task=True,
            require_live_master=True,
            require_fresh_permit=True,
        )


def test_completed_replay_is_historical_and_skips_current_authority(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    state = lifecycle_harness["state"]
    reset_invocations = state["reset_invocations"]
    relaunch_invocations = state["relaunch_invocations"]
    # Model later task progress plus legitimate writer and plan-generation
    # rollover. Historical replay must not consult or mutate any of them.
    lifecycle_harness["context"]["task"].revision = 99
    lifecycle_harness["context"]["writer"].fencing_token = 42
    lifecycle_harness["context"]["snapshot"].plan_root_cid = "plan:future"
    monkeypatch.setattr(
        program,
        "_retry_lifecycle_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "historical replay consulted live authority"
        ),
    )

    replay = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )

    assert replay == receipt
    assert state["reset_invocations"] == reset_invocations
    assert state["relaunch_invocations"] == relaunch_invocations


def test_completed_parent_without_durable_reset_anchor_fails_replay_and_inspection(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    monkeypatch.setattr(
        program,
        "_verify_parent_retry_reset_anchor",
        REAL_VERIFY_PARENT_RETRY_RESET_ANCHOR,
    )

    with pytest.raises(Exception):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
        )
    inspection = program._retry_reset_inspection()
    assert inspection["ok"] is False
    assert "retry-reset journal" in inspection["error"]


def test_completed_parent_rejects_mismatched_reset_journal_and_event(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    request = lifecycle_harness["context"]["request"]
    parent_path = program._retry_lifecycle_journal_path(request)
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    reset_path = Path(parent["retry_reset_anchor"]["journal_path"])
    reset_path.parent.mkdir(parents=True, exist_ok=True)
    reset_path.write_text(
        json.dumps(
            {
                "schema": "forged-reset-journal@1",
                "phase": "completed",
                "journal_key_cid": reset_path.stem,
                "completion_event": {
                    "event_cid": "sha256:" + "0" * 64,
                    "sequence": 2,
                    "revision": 5,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        program,
        "_verify_parent_retry_reset_anchor",
        REAL_VERIFY_PARENT_RETRY_RESET_ANCHOR,
    )

    with pytest.raises(Exception):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
        )
    inspection = program._retry_reset_inspection()
    assert inspection["ok"] is False
    assert inspection["error"]


def test_drained_journal_fences_launch_while_reset_lock_is_released(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_at_release_boundary(phase: str) -> None:
        if phase == "drained":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_at_release_boundary,
        )

    inspection = program._retry_reset_inspection()

    assert not inspection["ok"]
    assert inspection["incomplete"][0]["phase"] == "drained"
    # ``preflight_checks`` installs this exact inspection as a required launch
    # check, so cmd_launch cannot cross the lock-release/reset window.
    assert inspection["incomplete"][0]["kind"] == "retry_lifecycle"


def test_checkout_change_after_lease_acquisition_blocks_reset(
    lifecycle_harness: dict[str, Any],
) -> None:
    state = lifecycle_harness["state"]

    def race(phase: str) -> None:
        if phase == "checkout_leases_acquired":
            changed = [dict(item) for item in state["checkout_binding"]]
            changed[0]["head_tree"] = "e" * 40
            state["checkout_binding"] = changed

    with pytest.raises(RuntimeError, match="changed while leased"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=race,
        )

    assert state["reset_invocations"] == 0
    assert state["relaunch_invocations"] == 0


def test_checkout_change_before_relaunch_blocks_launch(
    lifecycle_harness: dict[str, Any],
) -> None:
    state = lifecycle_harness["state"]

    def race(phase: str) -> None:
        if phase == "reset_committed":
            changed = [dict(item) for item in state["checkout_binding"]]
            changed[-1]["head_commit"] = "e" * 40
            state["checkout_binding"] = changed

    with pytest.raises(RuntimeError, match="changed while leased"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=race,
        )

    assert state["reset_invocations"] == 1
    assert state["relaunch_invocations"] == 0


def test_live_exact_checkout_lease_owner_cannot_be_adopted(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop(phase: str) -> None:
        if phase == "drained":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="drained"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    request = lifecycle_harness["context"]["request"]
    journal_path = program._retry_lifecycle_journal_path(request)
    journal = program._read_retry_lifecycle_journal(journal_path, request=request)
    binding = journal["checkout_binding"][0]
    foreign_owner = {
        "pid": 901,
        "boot_id": "boot:test",
        "start_ticks": 250,
        "cmdline_sha256": "sha256:" + "9" * 64,
        "argv": ["python", "foreign-retry-owner"],
    }
    foreign = program._new_retry_checkout_lease(journal, binding, foreign_owner)
    program._create_retry_checkout_lock(Path(binding["lock_path"]), foreign)
    lifecycle_harness["state"]["live_owner_pids"].add(901)

    with pytest.raises(RuntimeError, match="lease owner is still live"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )

    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_foreign_checkout_lock_is_rejected_without_replacement(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop(phase: str) -> None:
        if phase == "drained":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="drained"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )
    lock_path = Path(journal["checkout_binding"][0]["lock_path"])
    encoded = b'{"schema":"foreign-checkout-lock@1"}\n'
    descriptor = program.os.open(
        lock_path,
        program.os.O_CREAT | program.os.O_EXCL | program.os.O_WRONLY,
        0o600,
    )
    try:
        program.os.write(descriptor, encoded)
        program.os.fsync(descriptor)
    finally:
        program.os.close(descriptor)

    with pytest.raises(RuntimeError, match="foreign or malformed"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )

    assert lock_path.read_bytes() == encoded
    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_checkout_mutation_lease_rejects_a_symlink(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop(phase: str) -> None:
        if phase == "drained":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="drained"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )
    lock_path = Path(journal["checkout_binding"][0]["lock_path"])
    target = lock_path.with_name("foreign-checkout-target.json")
    target.write_text("{}\n", encoding="utf-8")
    lock_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="retry checkout mutation lease"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )

    assert lock_path.is_symlink()
    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_checkout_common_directory_error_names_exact_path_mode_and_owner(
    lifecycle_harness: dict[str, Any],
) -> None:
    binding = lifecycle_harness["context"]["checkout_binding"][0]
    common_dir = Path(binding["lock_path"]).parent
    common_dir.chmod(0o770)

    with pytest.raises(RuntimeError) as captured:
        program._assert_retry_checkout_lock_authority(
            binding,
            Path(binding["lock_path"]),
            require_guard=False,
        )

    detail = str(captured.value)
    assert f"path={common_dir}" in detail
    assert "mode=0770" in detail
    assert f"uid={common_dir.stat().st_uid}" in detail
    assert f"gid={common_dir.stat().st_gid}" in detail


def test_dead_checkout_lease_owner_is_adopted_with_a_bound_generation(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop(phase: str) -> None:
        if phase == "leased":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="leased"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    lifecycle_harness["state"]["current_owner"] = {
        "pid": 901,
        "boot_id": "boot:test",
        "start_ticks": 251,
        "cmdline_sha256": "sha256:" + "8" * 64,
        "argv": ["python", "recover-task", "--adopt"],
    }

    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )

    assert receipt["schema"] == program.RETRY_LIFECYCLE_RECEIPT_SCHEMA
    assert {item["generation"] for item in journal["checkout_leases"]} == {2}
    assert all(len(item["owner_history"]) == 2 for item in journal["checkout_leases"])


def test_checkout_adoption_reconciles_crash_after_physical_replace(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_leased(phase: str) -> None:
        if phase == "leased":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="leased"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_leased,
        )
    lifecycle_harness["state"]["current_owner"] = {
        "pid": 903,
        "boot_id": "boot:test",
        "start_ticks": 253,
        "cmdline_sha256": "sha256:" + "6" * 64,
        "argv": ["python", "recover-task", "--physical-adopt"],
    }
    crash_phase = "checkout_lease_adopted_physical:accelerator"

    def stop_after_replace(phase: str) -> None:
        if phase == crash_phase:
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_after_replace,
        )

    program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )
    assert {item["generation"] for item in journal["checkout_leases"]} == {2}


@pytest.mark.parametrize(
    "crash_phase",
    (
        "checkout_release_artifact_linked:accelerator",
        "checkout_lease_unlinked:accelerator",
    ),
)
def test_checkout_release_tombstone_replays_around_unlink(
    lifecycle_harness: dict[str, Any],
    crash_phase: str,
) -> None:
    def stop(phase: str) -> None:
        if phase == crash_phase:
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )

    assert receipt["checkout_release_receipt"]["schema"] == (
        program.RETRY_CHECKOUT_RELEASE_RECEIPT_SCHEMA
    )
    assert all(
        item["state"] == "released"
        and Path(item["tombstone_path"]).is_file()
        for item in journal["checkout_release_tombstones"]
    )
    assert lifecycle_harness["state"]["reset_invocations"] == 1
    assert len(lifecycle_harness["state"]["relaunch_effects"]) == 1


def test_partial_release_adopts_only_the_still_held_dead_owner_lease(
    lifecycle_harness: dict[str, Any],
) -> None:
    crash_phase = "checkout_lease_unlinked:accelerator"

    def stop(phase: str) -> None:
        if phase == crash_phase:
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    lifecycle_harness["state"]["current_owner"] = {
        "pid": 902,
        "boot_id": "boot:test",
        "start_ticks": 252,
        "cmdline_sha256": "sha256:" + "7" * 64,
        "argv": ["python", "recover-task", "--release-adopt"],
    }

    program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )
    generations = {
        item["repository_role"]: item["generation"]
        for item in journal["checkout_leases"]
    }

    assert generations == {"accelerator": 1, "parent": 2}
    assert all(
        item["state"] == "released"
        for item in journal["checkout_release_tombstones"]
    )


def test_partial_release_reconciles_crash_after_adoption_replace(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_after_first_release(phase: str) -> None:
        if phase == "checkout_lease_unlinked:accelerator":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="checkout_lease_unlinked:accelerator"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_after_first_release,
        )
    lifecycle_harness["state"]["current_owner"] = {
        "pid": 904,
        "boot_id": "boot:test",
        "start_ticks": 254,
        "cmdline_sha256": "sha256:" + "5" * 64,
        "argv": ["python", "recover-task", "--release-physical-adopt"],
    }
    crash_phase = "checkout_release_adopted_physical:parent"

    def stop_after_adoption_replace(phase: str) -> None:
        if phase == crash_phase:
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_after_adoption_replace,
        )

    program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(
            lifecycle_harness["context"]["request"]
        )
    )
    assert {
        item["repository_role"]: item["generation"]
        for item in journal["checkout_leases"]
    } == {"accelerator": 1, "parent": 2}


def test_durable_checkout_release_receipt_is_reused_after_crash(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop(phase: str) -> None:
        if phase == "checkout_released":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="checkout_released"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    request = lifecycle_harness["context"]["request"]
    path = program._retry_lifecycle_journal_path(request)
    before = program._read_retry_lifecycle_journal(path, request=request)
    durable_release = dict(before["checkout_release_receipt"])

    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    after = program._read_retry_lifecycle_journal(path, request=request)

    assert after["checkout_release_receipt"] == durable_release
    assert receipt["checkout_release_receipt"] == durable_release


def test_completed_retry_rejects_a_recreated_owned_checkout_lock(
    lifecycle_harness: dict[str, Any],
) -> None:
    program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    request = lifecycle_harness["context"]["request"]
    journal_path = program._retry_lifecycle_journal_path(request)
    journal = program._read_retry_lifecycle_journal(journal_path, request=request)
    released = journal["checkout_release_tombstones"][0]
    program.os.link(released["tombstone_path"], released["lock_path"])

    with pytest.raises(RuntimeError, match="remains at its lock path"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )
    inspection = program._retry_reset_inspection()
    assert inspection["ok"] is False
    assert "remains at its lock path" in inspection["error"]


def test_completed_retry_requires_every_durable_release_artifact(
    lifecycle_harness: dict[str, Any],
) -> None:
    program._run_retry_lifecycle(
        lifecycle_harness["request_file"], drain_timeout_seconds=1
    )
    request = lifecycle_harness["context"]["request"]
    journal_path = program._retry_lifecycle_journal_path(request)
    journal = program._read_retry_lifecycle_journal(journal_path, request=request)
    artifact_path = Path(journal["checkout_release_tombstones"][0]["tombstone_path"])
    artifact_path.unlink()

    with pytest.raises(RuntimeError, match="release artifact is missing"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )
    inspection = program._retry_reset_inspection()
    assert inspection["ok"] is False
    assert "release artifact is missing" in inspection["error"]


def test_retry_lifecycle_rejects_a_master_without_a_dedicated_session(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(program, "_process_session_id", lambda _pid: None)

    with pytest.raises(RuntimeError, match="dedicated-session master"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
        )

    assert lifecycle_harness["state"]["master_live"] is True
    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_retry_lifecycle_rejects_an_uncaptured_late_session_member(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(program, "_process_session_members", lambda _sid: (888,))
    journal = program._new_retry_lifecycle_journal(lifecycle_harness["context"])
    lifecycle_harness["state"]["master_live"] = False

    with pytest.raises(RuntimeError, match="session still owns live processes"):
        program._assert_captured_retry_tree_dead(journal)

    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_finite_retry_permit_prepares_durable_execution_intent_before_drain(
    lifecycle_harness: dict[str, Any],
) -> None:
    request = lifecycle_harness["context"]["request"]
    request.authorization.expires_at_ms = (
        program.time.time_ns() // 1_000_000 + 60_000
    )

    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )
    journal = program._read_retry_lifecycle_journal(
        program._retry_lifecycle_journal_path(request), request=request
    )

    assert receipt["execution_intent_cid"]
    assert journal["execution_intent"]["execution_intent_cid"] == receipt[
        "execution_intent_cid"
    ]
    assert lifecycle_harness["state"]["reset_invocations"] == 1


def test_parent_journal_without_durable_event_blocks_before_signal_after_expiry(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = lifecycle_harness["context"]["request"]
    journal = program._new_retry_lifecycle_journal(
        lifecycle_harness["context"]
    )
    path = program._retry_lifecycle_journal_path(request)
    program._durable_retry_lifecycle_write(path, journal)
    monkeypatch.setattr(
        program.time,
        "time_ns",
        lambda: int(request.authorization.expires_at_ms) * 1_000_000,
    )

    with pytest.raises(RuntimeError, match="execution-intent binding"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )

    assert lifecycle_harness["state"]["master_live"] is True
    assert lifecycle_harness["state"]["reset_invocations"] == 0


def test_forged_parent_execution_binding_blocks_before_signal(
    lifecycle_harness: dict[str, Any],
) -> None:
    def stop_after_parent(phase: str) -> None:
        if phase == "prepared":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="prepared"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop_after_parent,
        )
    request = lifecycle_harness["context"]["request"]
    path = program._retry_lifecycle_journal_path(request)
    journal = program._read_retry_lifecycle_journal(path, request=request)
    journal["execution_intent"]["preparation_event"]["event_cid"] = (
        content_identity({"forged": "event-envelope"})
    )
    program._durable_retry_lifecycle_write(path, journal)

    with pytest.raises(RuntimeError, match="durable PREPARED event"):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"], drain_timeout_seconds=1
        )

    assert lifecycle_harness["state"]["master_live"] is True
    assert lifecycle_harness["state"]["reset_invocations"] == 0


@pytest.mark.parametrize(
    "crash_phase",
    (
        "execution_intent_event_appended",
        "execution_intent_prepared",
        "prepared",
        "draining",
        "drained",
    ),
)
def test_durable_intent_permit_recovers_after_arbitrary_clock_advance(
    lifecycle_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    crash_phase: str,
) -> None:
    clock_ms = {"value": 1_000}
    monkeypatch.setattr(
        program.time,
        "time_ns",
        lambda: clock_ms["value"] * 1_000_000,
    )

    def stop(phase: str) -> None:
        if phase == crash_phase:
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match=crash_phase):
        program._run_retry_lifecycle(
            lifecycle_harness["request_file"],
            drain_timeout_seconds=1,
            fault_injector=stop,
        )
    clock_ms["value"] = 9_999_999_999_999
    receipt = program._run_retry_lifecycle(
        lifecycle_harness["request_file"],
        drain_timeout_seconds=1,
    )

    assert receipt["schema"] == program.RETRY_LIFECYCLE_RECEIPT_SCHEMA
    assert lifecycle_harness["state"]["reset_invocations"] == 1


def test_event_only_execution_intent_blocks_inspection_preflight_and_doctor(
    real_execution_intent_boundary: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = real_execution_intent_boundary

    def crash_after_event(phase: str) -> None:
        if phase == "execution_intent_event_appended":
            raise InjectedCrash(phase)

    with pytest.raises(InjectedCrash, match="execution_intent_event_appended"):
        prepare_duckdb_retry_reset_execution_intent(
            harness["request"],
            trusted_policy=harness["policy"],
            trusted_owner=harness["owner"],
            parent_prepared=harness["parent_prepared"],
            parent_journal_path=harness["parent_path"],
            request_file_bytes=harness["request_file_bytes"],
            fault_injector=crash_after_event,
        )

    preparation_events = [
        event
        for event in harness["source"].events(cursor=0, limit=1_000).events
        if event["event_type"] == "retry_reset_execution_intent_prepared"
    ]
    assert len(preparation_events) == 1
    assert not harness["parent_path"].exists()
    assert not (
        harness["runtime"] / "duckdb-retry-reset/execution-intents"
    ).exists()

    harness["stop_master"]()
    assert harness["master"].poll() is not None
    assert not program.MASTER_PID.exists()
    assert program._process_session_members(harness["master"].pid) == ()

    incomplete = inspect_incomplete_retry_resets(harness["runtime"])
    assert len(incomplete) == 1
    assert incomplete[0]["phase"] == "execution_intent_event_appended"
    assert incomplete[0]["request_id"] == harness["request"].request_id

    parent_inspection = program._retry_reset_inspection()
    assert parent_inspection["ok"] is False
    assert parent_inspection["error"] == ""
    assert parent_inspection["incomplete"] == list(incomplete)

    checks = {
        check["name"]: check for check in program.preflight_checks(require_clean=False)
    }
    retry_check = checks["retry_reset_journal_recovery"]
    assert retry_check["required"] is True
    assert retry_check["ok"] is False
    assert "execution_intent_event_appended" in retry_check["detail"]
    assert checks["runtime_namespace_free"]["ok"] is True

    capsys.readouterr()
    assert program.cmd_doctor(SimpleNamespace(stale_seconds=1_200.0)) == 2
    doctor = json.loads(capsys.readouterr().out)
    recovery_findings = [
        finding
        for finding in doctor["findings"]
        if finding["kind"] == "retry_reset_recovery_incomplete"
    ]
    assert len(recovery_findings) == 1
    assert recovery_findings[0]["severity"] == "critical"
    assert "execution_intent_event_appended" in recovery_findings[0]["detail"]

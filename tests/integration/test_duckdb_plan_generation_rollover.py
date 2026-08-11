"""Integration tests for governed plan/runtime-generation rollover (DQK-083).

Acceptance coverage:

* A changed plan is never materialized over the active database
* Completing DQK-083 only installs the lifecycle owner; it cannot stand in for
  DQK-103 runtime activation or DQK-081 plan approval
* The lifecycle command consumes accepted signed/CID-bound DuckDB plan-revision
  and environment-generation rows independently of the seed TASKS tuple and
  refuses unapproved aliases or artifacts
* JSON/Markdown/formal-source/environment files are transport projections only
  and cannot authorize rollover
* Old-generation writers and daemons are fenced before new tasks become ready
* Static execution slices, exact source roots, sealed interpreter, extension
  profile, and environment digest are regenerated from the accepted revision
  and the new master is identity-bound
* Crash injection at every drain/materialize/launch/retire boundary is
  idempotently recoverable
* Restart after prior task merges verifies completion and merge receipts rather
  than requiring seed HEAD
* The rollover receipt binds old/new roots, database and environment identities,
  task population, writer epochs, process birth identities and signed authorization
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIFECYCLE_SCRIPT = _REPO_ROOT / "scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py"
_ROLLOVER_MODULE = (
    _REPO_ROOT / "ipfs_datasets_py/duckdb_control/generation_rollover.py"
)

# Prefer the sealed validator's accelerator checkout in nested worktrees.
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import generation_rollover as rollover
from ipfs_datasets_py.duckdb_control.generation_rollover import (
    ACTIVATION_SCHEMA,
    APPROVAL_GATE_TASK_ID,
    AUTHORITY_SURFACE,
    CRASH_BOUNDARIES,
    ENVIRONMENT_ROW_SCHEMA,
    JOURNAL_SCHEMA,
    LIFECYCLE_OWNER_TASK_ID,
    PLAN_REVISION_ROW_SCHEMA,
    PROGRAM_ID,
    ROLLOVER_RECEIPT_SCHEMA,
    RUNTIME_ACTIVATION_GATE_TASK_ID,
    CrashInjected,
    GenerationIdentity,
    GenerationRolloverError,
    MemoryAuthorityStore,
    WriterFenceState,
    authorize_rollover_from_files,
    build_environment_row,
    build_plan_revision_row,
    build_process_birth,
    execute_rollover,
    install_check,
    load_transport_projection,
    refuse_runtime_activation_without_permit,
    self_check,
    verify_completion_from_merge_receipts,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


TREE_ID = "b" * 40


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _old_generation() -> GenerationIdentity:
    old_plan = _digest("fixture-old-plan")
    return GenerationIdentity(
        generation_id="generation:fixture-old",
        plan_root_cid=old_plan,
        repository_tree_id=TREE_ID,
        database_path="/tmp/dqk083-fixture/control.duckdb",
        database_identity=_digest("fixture-old-db"),
        environment_digest=_digest("fixture-old-env"),
        environment_row_cid=_digest("fixture-old-env-row"),
        execution_slice_sha256=_digest("fixture-old-slice"),
        source_root_cid=_digest("fixture-old-source"),
        sealed_interpreter="/old/fixture/python",
        extension_profile_cid=_digest("fixture-old-ext"),
        writer_fence=WriterFenceState(
            writer_id="writer:fixture-old",
            fencing_token=5,
            epoch=2,
            generation_id="generation:fixture-old",
        ),
        task_population=("DQK-001", "DQK-007", "DQK-056"),
        master_birth=build_process_birth(
            pid=4242,
            boot_id="boot-fixture",
            start_ticks=100,
            argv=("/old/fixture/python", "-m", "old.master"),
        ),
        retired=False,
    )


def _accepted_plan_row(
    *,
    plan_root_cid: str | None = None,
    base_plan_root_cid: str | None = None,
    status: str = "accepted",
    task_population: tuple[str, ...] = ("DQK-001", "DQK-007", "DQK-056", "DQK-080"),
) -> dict[str, Any]:
    old = _old_generation()
    return build_plan_revision_row(
        plan_root_cid=plan_root_cid or _digest("fixture-new-plan"),
        base_plan_root_cid=base_plan_root_cid or old.plan_root_cid,
        repository_tree_id=TREE_ID,
        repository_id="repository:fixture-dqk-083",
        task_population=task_population,
        execution_slice_sha256=_digest("fixture-new-slice"),
        source_root_cid=_digest("fixture-new-source"),
        approval_receipt_cid=_digest("fixture-approval"),
        authorization_cid=_digest("fixture-authorization"),
        reviewer_id="reviewer:fixture-independent",
        status=status,
        proposal_ids=("proposal:1",),
        terminal_receipt_cids=(_digest("fixture-terminal-1"),),
    )


def _accepted_env_row(
    *,
    environment_digest: str | None = None,
    status: str = "accepted",
) -> dict[str, Any]:
    return build_environment_row(
        environment_digest=environment_digest or _digest("fixture-new-env"),
        sealed_interpreter="/sealed/fixture/python3.12",
        extension_profile_cid=_digest("fixture-new-ext"),
        environment_root="/tmp/dqk083-fixture/candidate-env",
        candidate_receipt_cid=_digest("fixture-candidate-receipt"),
        status=status,
    )


def _populated_store(
    *,
    plan_status: str = "accepted",
    env_status: str = "accepted",
    plan_root: str | None = None,
) -> tuple[MemoryAuthorityStore, dict[str, Any], dict[str, Any]]:
    store = MemoryAuthorityStore()
    store.set_seed_tasks_tuple("DQK-083", "DQK-SEED-ALIAS", "NOT-AUTHORITY")
    store.set_active_generation(_old_generation())
    plan = _accepted_plan_row(status=plan_status, plan_root_cid=plan_root)
    env = _accepted_env_row(status=env_status)
    store.put_plan_revision(plan)
    store.put_environment_generation(env)
    store.put_terminal_receipt(
        {"receipt_cid": _digest("fixture-terminal-1"), "task_id": "DQK-001"}
    )
    store.put_merge_receipt(
        {
            "receipt_cid": _digest("fixture-merge-007"),
            "task_id": "DQK-007",
            "status": "merged",
            "merge_commit": "c" * 40,
        }
    )
    return store, plan, env


def _write_authority_dir(
    root: Path,
    *,
    plan: dict[str, Any],
    env: dict[str, Any],
    active: GenerationIdentity | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    active_gen = active or _old_generation()
    (root / "active_generation.json").write_text(
        json.dumps(active_gen.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "plan_revision_accepted.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "environment_accepted.json").write_text(
        json.dumps(env, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "merge_receipt_dqk007.json").write_text(
        json.dumps(
            {
                "receipt_cid": _digest("fixture-merge-007"),
                "task_id": "DQK-007",
                "status": "merged",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "terminal_receipt_1.json").write_text(
        json.dumps(
            {"receipt_cid": _digest("fixture-terminal-1"), "task_id": "DQK-001"},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "seed_TASKS.json").write_text(
        json.dumps({"TASKS": ["DQK-083", "FORGED-SEED"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# Expected outputs / install surface
# ---------------------------------------------------------------------------


def test_expected_outputs_exist() -> None:
    assert _ROLLOVER_MODULE.is_file()
    assert _LIFECYCLE_SCRIPT.is_file()
    assert Path(__file__).is_file()


def test_install_check_does_not_activate() -> None:
    report = install_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == LIFECYCLE_OWNER_TASK_ID == "DQK-083"
    assert report["lifecycle_owner_installed"] is True
    assert report["activates_runtime_generation"] is False
    assert report["substitutes_for_plan_approval"] is False
    assert report["substitutes_for_runtime_activation"] is False
    assert report["approval_gate_task_id"] == APPROVAL_GATE_TASK_ID == "DQK-081"
    assert (
        report["runtime_activation_gate_task_id"]
        == RUNTIME_ACTIVATION_GATE_TASK_ID
        == "DQK-103"
    )
    assert report["seed_tasks_tuple_is_authority"] is False
    assert report["transport_projections_cannot_authorize"] is True


def test_self_check_passes() -> None:
    report = self_check()
    assert report["ok"] is True
    assert report["files_refused"] is True
    assert report["unapproved_refused"] is True
    assert report["overwrite_refused"] is True
    assert report["activation_refused"] is True
    assert report["crash_boundaries_recovered"] == list(CRASH_BOUNDARIES)
    assert report["seed_head_required"] is False
    assert report["materialized_over_active"] is False


# ---------------------------------------------------------------------------
# Authority: signed/CID-bound rows; refuse unapproved; ignore seed TASKS
# ---------------------------------------------------------------------------


def test_happy_path_rollover_from_authority_rows() -> None:
    store, plan, env = _populated_store()
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id="test-happy-path",
        owner_birth=build_process_birth(
            pid=9001,
            boot_id="boot-test",
            start_ticks=1,
            argv=("/lifecycle/python", "rollover"),
        ),
    )
    assert result["ok"] is True
    assert result["activates_runtime_generation"] is False
    assert result["materialized_over_active"] is False
    assert result["old_writers_fenced_before_ready"] is True
    assert result["substitutes_for_plan_approval"] is False
    assert result["substitutes_for_runtime_activation"] is False

    receipt = result["receipt"]
    verify_signature(receipt, noun="rollover_receipt")
    assert receipt["schema"] == ROLLOVER_RECEIPT_SCHEMA
    assert receipt["owner_task_id"] == "DQK-083"
    assert receipt["activates_runtime_generation"] is False

    active = store.get_active_generation()
    assert active is not None
    assert active.plan_root_cid == plan["plan_root_cid"]
    assert active.environment_digest == env["environment_digest"]
    assert active.execution_slice_sha256 == plan["execution_slice_sha256"]
    assert active.source_root_cid == plan["source_root_cid"]
    assert active.sealed_interpreter == env["sealed_interpreter"]
    assert active.extension_profile_cid == env["extension_profile_cid"]
    assert active.master_birth is not None
    assert active.master_birth.argv[0] == env["sealed_interpreter"]
    assert os.path.normpath(active.database_path) != os.path.normpath(
        _old_generation().database_path
    )


def test_seed_tasks_tuple_is_not_authority() -> None:
    store, plan, env = _populated_store()
    assert "DQK-SEED-ALIAS" in store.seed_tasks_tuple
    # Rollover succeeds from authority rows despite seed aliases.
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id="test-seed-ignored",
    )
    assert result["ok"] is True
    # Task population comes from the plan revision row, not seed TASKS.
    assert "DQK-SEED-ALIAS" not in result["receipt"]["new_generation"]["task_population"]
    assert "DQK-080" in result["receipt"]["new_generation"]["task_population"]


def test_refuses_unapproved_plan_revision() -> None:
    store, _plan, env = _populated_store(plan_status="non_active")
    # Replace with explicitly non_active row and try to use it.
    unapproved = _accepted_plan_row(status="non_active")
    store.put_plan_revision(unapproved)
    with pytest.raises(GenerationRolloverError, match="unapproved"):
        execute_rollover(
            store,
            plan_revision_row_cid=unapproved["row_cid"],
            environment_row_cid=env["row_cid"],
            operation_id="test-unapproved",
        )


def test_refuses_rejected_environment() -> None:
    store, plan, _env = _populated_store()
    rejected = _accepted_env_row(status="rejected")
    store.put_environment_generation(rejected)
    with pytest.raises(GenerationRolloverError, match="unapproved environment"):
        execute_rollover(
            store,
            plan_revision_row_cid=plan["row_cid"],
            environment_row_cid=rejected["row_cid"],
            operation_id="test-rejected-env",
        )


def test_refuses_missing_authority_row_cid() -> None:
    store, plan, env = _populated_store()
    with pytest.raises(GenerationRolloverError, match="not present in authority"):
        execute_rollover(
            store,
            plan_revision_row_cid=_digest("missing-row"),
            environment_row_cid=env["row_cid"],
            operation_id="test-missing",
        )


def test_refuses_forged_signature() -> None:
    store, plan, env = _populated_store()
    forged = dict(plan)
    forged["signature"] = "sha256:" + "0" * 64
    with pytest.raises(GenerationRolloverError, match="signature"):
        store.put_plan_revision(forged)


# ---------------------------------------------------------------------------
# Files are transport only
# ---------------------------------------------------------------------------


def test_files_cannot_authorize_rollover(tmp_path: Path) -> None:
    plan = _accepted_plan_row()
    path = tmp_path / "forged-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(GenerationRolloverError, match="transport projections"):
        authorize_rollover_from_files(path)

    md = tmp_path / "plan.md"
    md.write_text("# forged plan\n", encoding="utf-8")
    with pytest.raises(GenerationRolloverError, match="transport projections"):
        authorize_rollover_from_files(md)

    envf = tmp_path / "environment.txt"
    envf.write_text("SEALED_INTERPRETER=/evil\n", encoding="utf-8")
    with pytest.raises(GenerationRolloverError, match="transport projections"):
        authorize_rollover_from_files(envf)


def test_transport_projection_loads_but_is_not_authority(tmp_path: Path) -> None:
    plan = _accepted_plan_row()
    path = tmp_path / "transport.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    projection = load_transport_projection(path)
    assert projection["transport_only"] is True
    assert projection["authority"] is False
    assert projection["body"]["row_cid"] == plan["row_cid"]


def test_lifecycle_cli_refuses_transport_only(tmp_path: Path) -> None:
    plan = _accepted_plan_row()
    path = tmp_path / "only-file.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_LIFECYCLE_SCRIPT),
            "rollover",
            "--transport-file",
            str(path),
            "--json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "transport" in combined.lower() or "authority" in combined.lower()


# ---------------------------------------------------------------------------
# Never materialize over active database
# ---------------------------------------------------------------------------


def test_never_materializes_over_active_database() -> None:
    store, plan, env = _populated_store()
    old = store.get_active_generation()
    assert old is not None
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id="test-no-overwrite",
    )
    new_path = result["receipt"]["new_generation"]["database_path"]
    assert os.path.normpath(new_path) != os.path.normpath(old.database_path)

    with pytest.raises(GenerationRolloverError, match="never materialized over"):
        store.materialize_generation(
            generation=GenerationIdentity(
                generation_id="generation:evil",
                plan_root_cid=plan["plan_root_cid"],
                repository_tree_id=TREE_ID,
                database_path=old.database_path,
                database_identity=_digest("evil"),
                environment_digest=env["environment_digest"],
                environment_row_cid=env["row_cid"],
                execution_slice_sha256=plan["execution_slice_sha256"],
                source_root_cid=plan["source_root_cid"],
                sealed_interpreter=env["sealed_interpreter"],
                extension_profile_cid=env["extension_profile_cid"],
                writer_fence=WriterFenceState(
                    writer_id="evil",
                    fencing_token=1,
                    epoch=9,
                    generation_id="generation:evil",
                ),
                task_population=("X",),
            ),
            active_database_path=old.database_path,
        )


def test_plan_change_with_no_materialize_refuses_active_rewrite() -> None:
    store, plan, env = _populated_store()
    with pytest.raises(GenerationRolloverError, match="materialize=False"):
        execute_rollover(
            store,
            plan_revision_row_cid=plan["row_cid"],
            environment_row_cid=env["row_cid"],
            operation_id="test-no-mat",
            materialize=False,
        )


# ---------------------------------------------------------------------------
# Writer fencing before new tasks ready
# ---------------------------------------------------------------------------


def test_old_writers_fenced_before_new_tasks_ready() -> None:
    store, plan, env = _populated_store()
    # Crash at materialize (after fence, before launch) to observe ordering.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        jpath = Path(tmp) / "fence.journal.json"
        try:
            execute_rollover(
                store,
                plan_revision_row_cid=plan["row_cid"],
                environment_row_cid=env["row_cid"],
                operation_id="test-fence-order",
                journal_path=jpath,
                crash_at="materialize",
            )
        except CrashInjected:
            pass
        journal = json.loads(jpath.read_text(encoding="utf-8"))
        assert "fence" in journal["completed_phases"]
        assert journal["effects"].get("old_writers_fenced") is True
        # New tasks must not be ready until launch completes.
        assert journal["effects"].get("new_tasks_ready") is not True
        assert "launch" not in journal["completed_phases"]
        # Completing the remaining phases marks tasks ready only after launch.
        resumed = execute_rollover(
            store,
            plan_revision_row_cid=plan["row_cid"],
            environment_row_cid=env["row_cid"],
            operation_id="test-fence-order",
            journal_path=jpath,
        )
        assert resumed["ok"] is True
        assert resumed["old_writers_fenced_before_ready"] is True
        final = json.loads(jpath.read_text(encoding="utf-8"))
        assert "launch" in final["completed_phases"]
        assert final["effects"].get("new_tasks_ready") is True


# ---------------------------------------------------------------------------
# Identity-bound master / regenerated bindings
# ---------------------------------------------------------------------------


def test_new_master_identity_bound_to_accepted_revision() -> None:
    store, plan, env = _populated_store()
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id="test-identity",
    )
    receipt = result["receipt"]
    new_g = receipt["new_generation"]
    master = receipt["new_master_birth"]
    argv = master["argv"]
    assert argv[0] == new_g["sealed_interpreter"] == env["sealed_interpreter"]
    assert new_g["plan_root_cid"] in argv
    assert new_g["environment_digest"] in argv
    assert new_g["execution_slice_sha256"] in argv
    assert new_g["extension_profile_cid"] in argv
    assert new_g["source_root_cid"] in argv
    assert new_g["execution_slice_sha256"] == plan["execution_slice_sha256"]
    assert new_g["source_root_cid"] == plan["source_root_cid"]
    assert new_g["environment_digest"] == env["environment_digest"]


# ---------------------------------------------------------------------------
# Crash injection recoverability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("boundary", list(CRASH_BOUNDARIES))
def test_crash_injection_idempotently_recoverable(
    boundary: str, tmp_path: Path
) -> None:
    store, plan, env = _populated_store()
    jpath = tmp_path / f"{boundary}.journal.json"
    op = f"test-crash-{boundary}"
    with pytest.raises(CrashInjected) as raised:
        execute_rollover(
            store,
            plan_revision_row_cid=plan["row_cid"],
            environment_row_cid=env["row_cid"],
            operation_id=op,
            journal_path=jpath,
            crash_at=boundary,
            owner_birth=build_process_birth(
                pid=7000,
                boot_id="boot-crash",
                start_ticks=1,
                argv=("/lifecycle/python", "rollover"),
            ),
        )
    assert raised.value.boundary == boundary
    assert jpath.is_file()

    resumed = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id=op,
        journal_path=jpath,
        owner_birth=build_process_birth(
            pid=7000,
            boot_id="boot-crash",
            start_ticks=1,
            argv=("/lifecycle/python", "rollover"),
        ),
    )
    assert resumed["ok"] is True
    assert resumed["receipt"]["schema"] == ROLLOVER_RECEIPT_SCHEMA

    replay = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id=op,
        journal_path=jpath,
        owner_birth=build_process_birth(
            pid=7000,
            boot_id="boot-crash",
            start_ticks=1,
            argv=("/lifecycle/python", "rollover"),
        ),
    )
    assert replay["idempotent_replay"] is True
    assert replay["receipt"]["receipt_cid"] == resumed["receipt"]["receipt_cid"]


# ---------------------------------------------------------------------------
# Restart verifies merge receipts, not seed HEAD
# ---------------------------------------------------------------------------


def test_restart_verifies_merge_receipts_not_seed_head() -> None:
    store, _plan, _env = _populated_store()
    report = verify_completion_from_merge_receipts(
        store,
        expected_task_ids=("DQK-007",),
        seed_head="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )
    assert report["ok"] is True
    assert report["seed_head_required"] is False
    assert report["authority"] == "merge_receipts"
    assert "DQK-007" in report["completed_task_ids"]


def test_restart_fails_without_merge_receipts() -> None:
    store = MemoryAuthorityStore()
    with pytest.raises(GenerationRolloverError, match="merge receipts"):
        verify_completion_from_merge_receipts(store, seed_head="a" * 40)


# ---------------------------------------------------------------------------
# Receipt bindings
# ---------------------------------------------------------------------------


def test_rollover_receipt_binds_required_identities() -> None:
    store, plan, env = _populated_store()
    owner = build_process_birth(
        pid=8001,
        boot_id="boot-bind",
        start_ticks=9,
        argv=("/lifecycle/python", "rollover"),
    )
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan["row_cid"],
        environment_row_cid=env["row_cid"],
        operation_id="test-receipt-bind",
        owner_birth=owner,
    )
    receipt = result["receipt"]
    verify_signature(receipt, noun="receipt")

    assert receipt["old_generation"]["plan_root_cid"] == _old_generation().plan_root_cid
    assert receipt["new_generation"]["plan_root_cid"] == plan["plan_root_cid"]
    assert receipt["new_generation"]["database_identity"]
    assert receipt["new_generation"]["environment_digest"] == env["environment_digest"]
    assert receipt["new_generation"]["task_population"] == list(plan["task_population"])
    assert receipt["old_writer_fence"]["epoch"] >= _old_generation().writer_fence.epoch
    assert receipt["new_writer_fence"]["epoch"] > _old_generation().writer_fence.epoch
    assert receipt["owner_birth"]["boot_id"] == "boot-bind"
    assert receipt["new_master_birth"]["pid"] > 0
    assert receipt["authorization_cid"] == plan["authorization_cid"]
    assert receipt["plan_revision_row_cid"] == plan["row_cid"]
    assert receipt["environment_row_cid"] == env["row_cid"]
    assert _digest("fixture-terminal-1") in receipt["carried_terminal_receipt_cids"]
    assert receipt["approval_gate_task_id"] == "DQK-081"
    assert receipt["runtime_activation_gate_task_id"] == "DQK-103"
    assert receipt["authority_surface"] == AUTHORITY_SURFACE


# ---------------------------------------------------------------------------
# Runtime activation / plan approval separation
# ---------------------------------------------------------------------------


def test_cannot_stand_in_for_runtime_activation() -> None:
    report = refuse_runtime_activation_without_permit(check_only=True)
    assert report["activated"] is False
    assert report["lifecycle_owner_installed"] is True
    with pytest.raises(GenerationRolloverError, match="DQK-103"):
        refuse_runtime_activation_without_permit(
            activation_permit_cid=_digest("forged-permit"),
            check_only=False,
        )


def test_environment_row_cannot_claim_runtime_activation() -> None:
    with pytest.raises(GenerationRolloverError, match="cannot activate"):
        build_environment_row(
            environment_digest=_digest("x"),
            sealed_interpreter="/py",
            extension_profile_cid=_digest("e"),
            environment_root="/env",
            candidate_receipt_cid=_digest("c"),
            activates_runtime_generation=True,
        )


# ---------------------------------------------------------------------------
# Lifecycle CLI
# ---------------------------------------------------------------------------


def test_lifecycle_install_check_cli() -> None:
    proc = subprocess.run(
        [sys.executable, str(_LIFECYCLE_SCRIPT), "install-check", "--json"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["lifecycle_owner_installed"] is True
    assert payload["activates_runtime_generation"] is False


def test_lifecycle_activate_runtime_check_does_not_activate() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(_LIFECYCLE_SCRIPT),
            "activate-runtime",
            "--check",
            "--json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema"] == ACTIVATION_SCHEMA
    assert payload["activated"] is False
    assert payload["lifecycle_owner_installed"] is True
    assert payload.get("dqk_083_activates_generation") is False


def test_lifecycle_rollover_cli(tmp_path: Path) -> None:
    plan = _accepted_plan_row()
    env = _accepted_env_row()
    authority = _write_authority_dir(tmp_path / "authority", plan=plan, env=env)
    journal = tmp_path / "rollover.journal.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_LIFECYCLE_SCRIPT),
            "rollover",
            "--authority-dir",
            str(authority),
            "--plan-revision-row-cid",
            plan["row_cid"],
            "--environment-row-cid",
            env["row_cid"],
            "--journal",
            str(journal),
            "--operation-id",
            "cli-test-rollover",
            "--json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["activates_runtime_generation"] is False
    assert payload["receipt"]["schema"] == ROLLOVER_RECEIPT_SCHEMA
    assert journal.is_file()


def test_lifecycle_rollover_check_self_check() -> None:
    proc = subprocess.run(
        [sys.executable, str(_LIFECYCLE_SCRIPT), "rollover", "--check", "--json"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["crash_boundaries_recovered"] == list(CRASH_BOUNDARIES)


def test_lifecycle_verify_merges_cli(tmp_path: Path) -> None:
    plan = _accepted_plan_row()
    env = _accepted_env_row()
    authority = _write_authority_dir(tmp_path / "authority", plan=plan, env=env)
    proc = subprocess.run(
        [
            sys.executable,
            str(_LIFECYCLE_SCRIPT),
            "verify-merges",
            "--authority-dir",
            str(authority),
            "--task-id",
            "DQK-007",
            "--seed-head",
            "a" * 40,
            "--json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["seed_head_required"] is False
    assert "DQK-007" in payload["completed_task_ids"]


def test_lifecycle_refuse_files_cli(tmp_path: Path) -> None:
    forged = tmp_path / "forged.md"
    forged.write_text("# not authority\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_LIFECYCLE_SCRIPT),
            "refuse-files",
            "--file",
            str(forged),
            "--json",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["authorized"] is False
    assert payload["transport_projections_cannot_authorize"] is True


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


def test_schema_constants() -> None:
    assert PLAN_REVISION_ROW_SCHEMA.endswith("plan-revision-authority-row@1")
    assert ENVIRONMENT_ROW_SCHEMA.endswith("environment-generation-authority-row@1")
    assert ROLLOVER_RECEIPT_SCHEMA.endswith("generation-rollover-receipt@1")
    assert JOURNAL_SCHEMA.endswith("generation-rollover-journal@1")
    assert PROGRAM_ID == "ipfs-datasets-duckdb-quack-v1"
    assert CRASH_BOUNDARIES == ("drain", "materialize", "launch", "retire")

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import ipfs_datasets_py.optimizers.logic_port_daemon as logic_port_daemon
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext
from ipfs_datasets_py.optimizers.logic_port_daemon import (
    DEFAULT_PLAN_DOCS,
    LogicPortArtifact,
    LogicPortDaemonConfig,
    LogicPortDaemonOptimizer,
    _repair_common_typescript_text_damage,
    build_arg_parser,
    extract_plan_tasks,
    parse_llm_patch_response,
)
from ipfs_datasets_py.optimizers.todo_daemon.core import ManagedDaemonSpec, check_daemon_health
from ipfs_datasets_py.optimizers.todo_daemon.legal_parser import (
    build_legal_parser_spec,
    check_legal_parser_health,
    legal_parser_launch_env,
)
from ipfs_datasets_py.optimizers.todo_daemon.logic_port import build_logic_port_spec, logic_port_launch_env
from ipfs_datasets_py.optimizers.todo_daemon.plans import (
    PlanTask,
    extract_plan_tasks as extract_generic_plan_tasks,
    replace_checkbox_mark,
    strip_daemon_task_board,
)


class FakeRouter:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return self.response


class SequencedRouter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


class FailingRouter:
    def generate_text(self, prompt, **kwargs):
        raise RuntimeError("no route")


class HangingRouter:
    def __init__(self):
        self.calls = []

    def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        time.sleep(30)
        return "{}"


def test_default_plan_docs_use_typescript_port_plan():
    assert DEFAULT_PLAN_DOCS == ("docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md",)


def test_reusable_todo_daemon_health_reports_logic_port_fields(tmp_path):
    daemon_dir = tmp_path / ".daemon"
    daemon_dir.mkdir()
    status_path = daemon_dir / "daemon.status.json"
    progress_path = daemon_dir / "daemon.progress.json"
    supervisor_path = daemon_dir / "supervisor.status.json"
    supervisor_pid_path = daemon_dir / "supervisor.pid"
    child_pid_path = daemon_dir / "daemon.pid"
    now = logic_port_daemon.datetime.now(logic_port_daemon.timezone.utc).isoformat()
    pid = os.getpid()
    status_path.write_text(
        json.dumps(
            {
                "heartbeat_at": now,
                "heartbeat_pid": pid,
                "proposal_transport": "worktree",
                "worktree_edit_timeout_seconds": 300,
                "auto_commit": True,
            }
        ),
        encoding="utf-8",
    )
    progress_path.write_text(
        json.dumps({"updated_at": now, "current_task": "Task checkbox-1: portable daemon"}),
        encoding="utf-8",
    )
    supervisor_path.write_text(
        json.dumps(
            {
                "updated_at": now,
                "status": "running",
                "supervisor_pid": pid,
                "daemon_pid": pid,
                "task_board_path": "docs/todo.md",
            }
        ),
        encoding="utf-8",
    )
    supervisor_pid_path.write_text(str(pid), encoding="utf-8")
    spec = ManagedDaemonSpec(
        name="example",
        schema="example.todo_daemon",
        repo_root=tmp_path,
        daemon_dir=daemon_dir,
        runner=("bash", "run_example_daemon.sh"),
        status_path=status_path,
        progress_path=progress_path,
        supervisor_status_path=supervisor_path,
        supervisor_pid_path=supervisor_pid_path,
        child_pid_path=child_pid_path,
        supervisor_out_path=daemon_dir / "supervisor.out",
        ensure_status_path=daemon_dir / "ensure.status.json",
        ensure_check_path=daemon_dir / "ensure-check.json",
        task_board_path=Path("docs/todo.md"),
    )

    health = check_daemon_health(spec, stale_after_seconds=180)

    assert health.exit_code == 0
    assert health.payload["alive"] is True
    assert health.payload["status"] == "running"
    assert health.payload["proposal_transport"] == "worktree"
    assert health.payload["worktree_edit_timeout_seconds"] == 300
    assert health.payload["current_task"] == "Task checkbox-1: portable daemon"
    assert health.payload["task_board_path"] == "docs/todo.md"


def test_logic_port_lifecycle_spec_is_reusable_and_keeps_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("PROPOSAL_TRANSPORT", raising=False)
    monkeypatch.delenv("WORKTREE_REPAIR_ATTEMPTS", raising=False)
    monkeypatch.delenv("AUTO_COMMIT", raising=False)
    monkeypatch.delenv("LOGIC_PORT_PROVIDER", raising=False)
    monkeypatch.delenv("PROVIDER", raising=False)

    spec = build_logic_port_spec(str(tmp_path))
    launch_env = logic_port_launch_env()

    assert spec.name == "logic-port"
    assert spec.runner == ("bash", "ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh")
    assert spec.task_board_path == Path("docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md")
    assert spec.tmux_session_name == "logic-port-daemon"
    assert "ipfs_datasets_py.optimizers.logic_port_daemon" in spec.daemon_process_match_all
    assert launch_env["PROPOSAL_TRANSPORT"] == "worktree"
    assert launch_env["WORKTREE_REPAIR_ATTEMPTS"] == "1"
    assert launch_env["AUTO_COMMIT"] == "1"
    assert launch_env["PROVIDER"] == ""


def test_legal_parser_lifecycle_spec_is_reusable_and_keeps_defaults(tmp_path, monkeypatch):
    for name in (
        "MODEL_NAME",
        "PROVIDER",
        "IPFS_DATASETS_PY_LLM_PROVIDER",
        "DAEMON_DIR",
        "OUTPUT_DIR",
        "RUN_SCRIPT",
        "LEGAL_PARSER_DAEMON_WORKTREE_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    spec = build_legal_parser_spec(str(tmp_path))
    launch_env = legal_parser_launch_env()

    assert spec.name == "legal-parser"
    assert spec.schema == "ipfs_datasets_py.legal_parser_daemon"
    assert spec.runner == ("bash", "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh")
    assert spec.status_path == Path("artifacts/legal_parser_optimizer_daemon/current_status.json")
    assert spec.progress_path == Path("artifacts/legal_parser_optimizer_daemon/progress_summary.json")
    assert spec.tmux_session_name == "legal-parser-daemon"
    assert spec.worktree_root == Path(".daemon/legal-parser-worktrees")
    assert "ipfs_datasets_py.optimizers.logic.deontic.parser_daemon" in spec.daemon_process_match_all
    assert launch_env["MODEL_NAME"] == "gpt-5.5"
    assert launch_env["PROVIDER"] == "llm_router"
    assert launch_env["IPFS_DATASETS_PY_LLM_PROVIDER"] == "codex_cli"


def test_reusable_todo_daemon_health_reports_legal_parser_legacy_fields(tmp_path, monkeypatch):
    for name in (
        "DAEMON_DIR",
        "OUTPUT_DIR",
        "SUPERVISOR_STATUS_PATH",
        "SUPERVISOR_PID_PATH",
        "CHILD_PID_PATH",
        "ENSURE_STATUS_PATH",
        "CHECK_LOG_PATH",
        "SUPERVISOR_LOCK_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    spec = build_legal_parser_spec(str(tmp_path))
    now = logic_port_daemon.datetime.now(logic_port_daemon.timezone.utc).isoformat()
    pid = os.getpid()

    def write_spec_json(path: Path, payload: dict):
        resolved = spec.resolve(path)
        assert resolved is not None
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(json.dumps(payload), encoding="utf-8")

    write_spec_json(
        spec.status_path,
        {
            "heartbeat_at": now,
            "heartbeat_pid": pid,
            "cycle_index": 17,
            "phase": "requesting_worktree_edit",
            "phase_started_at": now,
            "model_name": "gpt-5.5",
            "provider": "llm_router",
            "proposal_transport": "worktree",
            "worktree_edit_timeout_seconds": 1200,
            "worktree_stale_after_seconds": 7200,
            "worktree_codex_sandbox": "danger-full-access",
            "repair_failed_tests_before_rollback": True,
            "failed_test_repair_attempts": 2,
            "worktree_no_child_stall_seconds": 999999,
            "dirty_legal_parser_targets_diff_summary": "clean",
        },
    )
    write_spec_json(
        spec.progress_path,
        {
            "stalled_metric_cycles": 0,
            "cycles_since_meaningful_progress": 1,
            "dirty_legal_parser_targets_diff_summary": "clean",
        },
    )
    write_spec_json(
        spec.supervisor_status_path,
        {
            "updated_at": now,
            "status": "running",
            "supervisor_pid": pid,
            "formal_logic_goal": "encoder decoder IR syntax checks across theorem provers",
            "agentic_acceptance_stall_cycles": 3,
            "agentic_state_path": "artifacts/legal_parser_optimizer_daemon/agentic_state.json",
        },
    )
    write_spec_json(
        spec.ensure_status_path,
        {
            "status": "already_running",
            "checked_at": now,
            "wrapper_pid": None,
            "supervisor_pid_alive": True,
        },
    )
    write_spec_json(
        Path("artifacts/legal_parser_optimizer_daemon/agentic_state.json"),
        {
            "dirty_legal_parser_targets_confirmed": False,
            "effective_phase_stall_threshold_seconds": 999999,
        },
    )

    health = check_legal_parser_health(spec, stale_after_seconds=180)

    assert health["alive"] is True
    assert health["cycle_index"] == 17
    assert health["phase"] == "requesting_worktree_edit"
    assert health["proposal_transport"] == "worktree"
    assert health["worktree_edit_timeout_seconds"] == 1200
    assert health["repair_failed_tests_before_rollback"] is True
    assert health["failed_test_repair_attempts"] == 2
    assert health["worktree_no_child_stall_seconds"] == 999999
    assert health["worktree_phase_worker_status"]["required"] is True
    assert health["formal_logic_goal"] == "encoder decoder IR syntax checks across theorem provers"
    assert health["agentic_acceptance_stall_cycles"] == 3
    assert health["ensure_status"] == "already_running"
    assert health["progress_dirty_legal_parser_targets_diff_summary"] == "clean"


def test_reusable_todo_plan_parser_strips_generated_board_and_replaces_marks():
    markdown = """# Plan

- [ ] Implement first reusable task
- [!] Keep blocked task

<!-- logic-port-daemon-task-board:start -->
- [ ] generated board item should be ignored
<!-- logic-port-daemon-task-board:end -->
"""

    tasks = extract_generic_plan_tasks(markdown)
    replaced = replace_checkbox_mark(strip_daemon_task_board(markdown), tasks[0], "x")

    assert tasks == [
        PlanTask("checkbox-1", "Implement first reusable task", "needed"),
        PlanTask("checkbox-2", "Keep blocked task", "blocked"),
    ]
    assert "generated board item should be ignored" not in strip_daemon_task_board(markdown)
    assert "- [x] Implement first reusable task" in replaced
    assert "- [!] Keep blocked task" in replaced


def test_cli_defaults_to_worktree_transport(monkeypatch):
    monkeypatch.delenv("LOGIC_PORT_DAEMON_PROPOSAL_TRANSPORT", raising=False)
    monkeypatch.delenv("LOGIC_PORT_DAEMON_WORKTREE_CODEX_SANDBOX", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_CODEX_SANDBOX", raising=False)
    monkeypatch.delenv("LOGIC_PORT_DAEMON_AUTO_COMMIT", raising=False)
    monkeypatch.delenv("LOGIC_PORT_DAEMON_AUTO_COMMIT_STARTUP_DIRTY", raising=False)
    monkeypatch.delenv("LOGIC_PORT_DAEMON_AUTO_COMMIT_BRANCH", raising=False)

    args = build_arg_parser().parse_args([])

    assert args.proposal_transport == "worktree"
    assert args.worktree_edit_timeout == 300
    assert args.worktree_stale_after == 7200
    assert args.worktree_codex_sandbox == "danger-full-access"
    assert args.worktree_repair_attempts == 1
    assert args.auto_commit is True
    assert args.auto_commit_startup_dirty is True
    assert args.auto_commit_branch == "main"


def test_supervisor_uses_worktree_transport_by_default():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts/ops/legal_data/run_logic_port_daemon.sh").read_text(encoding="utf-8")

    assert 'PROPOSAL_TRANSPORT="${PROPOSAL_TRANSPORT:-worktree}"' in script
    assert 'WORKTREE_EDIT_TIMEOUT_SECONDS="${WORKTREE_EDIT_TIMEOUT_SECONDS:-300}"' in script
    assert 'WORKTREE_STALE_AFTER_SECONDS="${WORKTREE_STALE_AFTER_SECONDS:-7200}"' in script
    assert 'WORKTREE_REPAIR_ATTEMPTS="${WORKTREE_REPAIR_ATTEMPTS:-1}"' in script
    assert 'AUTO_COMMIT="${AUTO_COMMIT:-1}"' in script
    assert 'AUTO_COMMIT_STARTUP_DIRTY="${AUTO_COMMIT_STARTUP_DIRTY:-1}"' in script
    assert 'AUTO_COMMIT_BRANCH="${AUTO_COMMIT_BRANCH:-main}"' in script
    assert '"proposal_transport": "$PROPOSAL_TRANSPORT"' in script
    assert '"worktree_edit_timeout_seconds": $WORKTREE_EDIT_TIMEOUT_SECONDS' in script
    assert '"worktree_repair_attempts": $WORKTREE_REPAIR_ATTEMPTS' in script
    assert '"auto_commit": $AUTO_COMMIT' in script
    assert '--auto-commit-branch "$AUTO_COMMIT_BRANCH"' in script
    assert '--proposal-transport "$PROPOSAL_TRANSPORT"' in script
    assert '--worktree-edit-timeout-seconds "$WORKTREE_EDIT_TIMEOUT_SECONDS"' in script
    assert '--worktree-stale-after-seconds "$WORKTREE_STALE_AFTER_SECONDS"' in script
    assert '--worktree-codex-sandbox "$WORKTREE_CODEX_SANDBOX"' in script
    assert '--worktree-root "$WORKTREE_ROOT"' in script
    assert '--worktree-repair-attempts "$WORKTREE_REPAIR_ATTEMPTS"' in script
    assert '--codex-bin "$CODEX_BIN"' in script
    assert 'SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="${SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE:-1}"' in script
    assert "startup_failure_maintenance_reason()" in script
    assert "startup_stale_failure:" in script
    assert "supervisor invoking startup failure maintenance" in script
    assert 'write_supervisor_status "agentic_maintenance_started" "$maintenance_id" "$maintenance_log" "$rc"' in script


def test_ensure_passes_startup_failure_maintenance_to_supervisor():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts/ops/legal_data/ensure_logic_port_daemon.sh").read_text(encoding="utf-8")

    assert 'SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="${SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE:-1}"' in script
    assert 'SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE="$SUPERVISOR_AGENTIC_STARTUP_FAILURE_MAINTENANCE"' in script
    assert '"agentic_startup_failure_maintenance": startup_failure_maintenance' in script


def test_check_script_reports_worktree_transport_health_fields():
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "scripts/ops/legal_data/check_logic_port_daemon.sh").read_text(encoding="utf-8")

    assert '"proposal_transport": status.get("proposal_transport")' in script
    assert '"worktree_edit_timeout_seconds": status.get("worktree_edit_timeout_seconds")' in script
    assert '"worktree_stale_after_seconds": status.get("worktree_stale_after_seconds")' in script
    assert '"worktree_codex_sandbox": status.get("worktree_codex_sandbox")' in script
    assert '"worktree_root": status.get("worktree_root")' in script
    assert '"worktree_repair_attempts": status.get("worktree_repair_attempts")' in script
    assert '"auto_commit": status.get("auto_commit")' in script
    assert '"auto_commit_startup_dirty": status.get("auto_commit_startup_dirty")' in script
    assert '"auto_commit_branch": status.get("auto_commit_branch")' in script


def test_parse_llm_patch_response_from_json():
    patch = "diff --git a/example.txt b/example.txt\n--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+new\n"
    response = json.dumps(
        {
            "summary": "Update example",
            "tasks": ["Task 0.1"],
            "patch": patch,
            "validation_commands": [["npx", "tsc", "--noEmit"]],
        }
    )

    artifact = parse_llm_patch_response(response)

    assert artifact.summary == "Update example"
    assert artifact.tasks == ["Task 0.1"]
    assert artifact.patch == patch
    assert artifact.validation_commands == [["npx", "tsc", "--noEmit"]]
    assert artifact.errors == []


def test_parse_llm_patch_response_with_file_edits():
    response = json.dumps(
        {
            "summary": "Edit docs",
            "tasks": ["small file edit"],
            "patch": "",
            "files": [{"path": "docs/example.md", "content": "# Example\n"}],
        }
    )

    artifact = parse_llm_patch_response(response)

    assert artifact.patch == ""
    assert artifact.files == [{"path": "docs/example.md", "content": "# Example\n"}]


def test_parse_llm_patch_response_from_fenced_diff():
    artifact = parse_llm_patch_response(
        "Here is the patch:\n```diff\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n```\n"
    )

    assert "diff --git" in artifact.patch
    assert artifact.errors == []


def test_parse_llm_patch_response_from_codex_event_stream():
    payload = {
        "summary": "Event JSON",
        "impact": "Codex event stream assistant content is parsed.",
        "patch": "",
        "files": [{"path": "src/lib/logic/event.ts", "content": "export const value = 1;\n"}],
    }
    response = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "example"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(payload)}],
                    },
                }
            ),
        ]
    )

    artifact = parse_llm_patch_response(response)

    assert artifact.summary == "Event JSON"
    assert artifact.files == [{"path": "src/lib/logic/event.ts", "content": "export const value = 1;\n"}]
    assert artifact.errors == []


def test_parse_llm_patch_response_marks_empty_codex_event_stream():
    response = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "example"}),
            json.dumps({"type": "turn.started"}),
        ]
    )

    artifact = parse_llm_patch_response(response)

    assert artifact.failure_kind == "codex_empty_event_stream"
    assert artifact.errors == ["Codex returned JSONL startup events without an assistant proposal."]


def test_run_command_timeout_kills_process_group(tmp_path):
    child_script = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=sys.stdout, stderr=sys.stderr)\n"
        "time.sleep(30)\n"
    )

    started = time.time()
    result = logic_port_daemon.run_command(
        (sys.executable, "-c", child_script),
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert result.returncode == 124
    assert "Command timed out after 1s" in result.stderr
    assert time.time() - started < 7


def test_worktree_transport_generates_file_edits_from_isolated_worktree(tmp_path, monkeypatch):
    plan = tmp_path / "docs" / "IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md"
    status = tmp_path / "docs" / "LOGIC_PORT_PARITY.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("- [ ] Port worktree direct edit runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    target_path = "src/lib/logic/worktreeFeature.ts"
    canonical_diff = "\n".join(
        [
            f"diff --git a/{target_path} b/{target_path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{target_path}",
            "@@ -0,0 +1 @@",
            "+export const worktreeFeature = true;",
            "",
        ]
    )
    calls = []

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        command = tuple(command)
        calls.append({"command": command, "cwd": Path(cwd), "timeout": timeout_seconds, "stdin": stdin})
        if command[:3] == ("git", "worktree", "prune"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "worktree", "list"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "worktree", "add"):
            Path(command[-2]).mkdir(parents=True, exist_ok=True)
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[0] == "codex-test":
            (Path(cwd) / target_path).parent.mkdir(parents=True, exist_ok=True)
            (Path(cwd) / target_path).write_text("export const worktreeFeature = true;\n", encoding="utf-8")
            (Path(cwd) / ".logic_port_worktree_proposal.json").write_text(
                json.dumps(
                    {
                        "summary": "Worktree direct edit",
                        "impact": "Adds a runtime file harvested from an isolated worktree.",
                        "tasks": ["Task checkbox-1: Port worktree direct edit runtime feature"],
                        "changed_files": [target_path],
                        "validation_commands": [["npx", "tsc", "--noEmit"]],
                    }
                ),
                encoding="utf-8",
            )
            return logic_port_daemon.CommandResult(command, 0, "edited", "")
        if command[:3] == ("git", "status", "--porcelain") and len(command) == 3:
            return logic_port_daemon.CommandResult(
                command,
                0,
                f"?? .logic_port_worktree_owner.json\n?? .logic_port_worktree_proposal.json\n M {target_path}\n",
                "",
            )
        if command[:3] == ("git", "status", "--porcelain"):
            return logic_port_daemon.CommandResult(command, 0, f" M {target_path}\n", "")
        if command[:3] == ("git", "diff", "--binary"):
            return logic_port_daemon.CommandResult(command, 0, canonical_diff, "")
        if command[:3] == ("git", "worktree", "remove"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        return logic_port_daemon.CommandResult(command, 0, "", "")

    monkeypatch.setattr(logic_port_daemon, "run_command", fake_run_command)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        proposal_transport="worktree",
        codex_bin="codex-test",
        worktree_edit_timeout_seconds=77,
        dry_run=True,
        validation_commands=tuple(),
    )

    result = LogicPortDaemonOptimizer(config).run_once(session_id="worktree-transport")

    assert result["valid"] is True
    assert result["artifact"]["proposal_transport"] == "worktree"
    assert result["artifact"]["files"] == [target_path]
    assert result["artifact"]["has_patch"] is False
    assert result["artifact"]["has_audit_diff"] is True
    assert result["artifact"]["uses_worktree_transport"] is True
    codex_call = next(call for call in calls if call["command"][0] == "codex-test")
    assert codex_call["timeout"] == 77
    assert "Edit files directly in this isolated worktree" in codex_call["stdin"]
    assert ".logic_port_worktree_proposal.json" in codex_call["stdin"]
    assert any(call["command"][:3] == ("git", "worktree", "remove") for call in calls)


def test_preflight_allows_worktree_runtime_patch_without_file_replacements(tmp_path):
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    patch = "\n".join(
        [
            "diff --git a/src/lib/logic/runtime.ts b/src/lib/logic/runtime.ts",
            "--- a/src/lib/logic/runtime.ts",
            "+++ b/src/lib/logic/runtime.ts",
            "@@ -1 +1 @@",
            "-export const oldValue = false;",
            "+export const oldValue = true;",
            "",
        ]
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        proposal_transport="worktree",
        prefer_file_edits=True,
    )
    artifact = LogicPortArtifact(patch=patch, proposal_transport="worktree")

    errors = LogicPortDaemonOptimizer(config)._preflight_artifact(artifact)

    assert not any("must use JSON `files`" in error for error in errors)


def test_worktree_validation_failure_repairs_in_temporary_worktree(tmp_path, monkeypatch):
    plan = tmp_path / "docs" / "IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md"
    status = tmp_path / "docs" / "LOGIC_PORT_PARITY.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    target_path = "src/lib/logic/worktreeRepair.ts"
    plan.parent.mkdir(parents=True, exist_ok=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (tmp_path / target_path).write_text("export const repaired = false;\n", encoding="utf-8")
    plan.write_text("- [ ] Port repair runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    base_diff = "\n".join(
        [
            f"diff --git a/{target_path} b/{target_path}",
            f"--- a/{target_path}",
            f"+++ b/{target_path}",
            "@@ -1 +1 @@",
            "-export const repaired = false;",
            "+export const repaired = 'bad';",
            "",
        ]
    )
    repaired_diff = base_diff.replace("+export const repaired = 'bad';", "+export const repaired = true;")
    command_calls = []
    diff_calls = {"count": 0}

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        command = tuple(command)
        cwd = Path(cwd)
        command_calls.append({"command": command, "cwd": cwd, "stdin": stdin, "timeout": timeout_seconds})
        if command[:3] == ("git", "status", "--porcelain") and cwd == tmp_path:
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "worktree", "prune"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "worktree", "list"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "worktree", "add"):
            Path(command[-2]).mkdir(parents=True, exist_ok=True)
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("npx", "prettier", "--write"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[0] == "codex-test":
            (cwd / target_path).write_text("export const repaired = true;\n", encoding="utf-8")
            (cwd / ".logic_port_worktree_repair.json").write_text(
                json.dumps(
                    {
                        "summary": "Repair validation failure in worktree",
                        "impact": "The failing candidate is repaired before touching the main worktree again.",
                        "tasks": ["Task checkbox-1: Port repair runtime feature"],
                        "changed_files": [target_path],
                    }
                ),
                encoding="utf-8",
            )
            return logic_port_daemon.CommandResult(command, 0, "repaired", "")
        if command[:3] == ("git", "status", "--porcelain") and len(command) == 3:
            return logic_port_daemon.CommandResult(
                command,
                0,
                f"?? .logic_port_worktree_owner.json\n?? .logic_port_worktree_repair.json\n M {target_path}\n",
                "",
            )
        if command[:3] == ("git", "status", "--porcelain"):
            return logic_port_daemon.CommandResult(command, 0, f" M {target_path}\n", "")
        if command[:3] == ("git", "add", "-N"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        if command[:3] == ("git", "diff", "--binary"):
            diff_calls["count"] += 1
            diff = base_diff if diff_calls["count"] == 1 else repaired_diff
            return logic_port_daemon.CommandResult(command, 0, diff, "")
        if command[:3] == ("git", "worktree", "remove"):
            return logic_port_daemon.CommandResult(command, 0, "", "")
        return logic_port_daemon.CommandResult(command, 0, "", "")

    monkeypatch.setattr(logic_port_daemon, "run_command", fake_run_command)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        proposal_transport="worktree",
        codex_bin="codex-test",
        worktree_repair_attempts=1,
        dry_run=False,
        validation_commands=tuple(),
    )
    optimizer = LogicPortDaemonOptimizer(config)
    monkeypatch.setattr(optimizer, "_typescript_replacement_preflight_errors", lambda edits: [])
    states = []
    monkeypatch.setattr(optimizer, "_write_status", lambda state, **details: states.append((state, details)))
    apply_calls = {"count": 0}

    def fake_apply_file_edits(edits):
        apply_calls["count"] += 1
        if apply_calls["count"] == 1:
            return (
                False,
                [logic_port_daemon.CommandResult(("npm", "run", "validate:logic-port"), 1, "", "expected repaired to be true")],
                [target_path],
            )
        assert edits == [{"path": target_path, "content": "export const repaired = true;\n"}]
        return (
            True,
            [logic_port_daemon.CommandResult(("npm", "run", "validate:logic-port"), 0, "ok", "")],
            [target_path],
        )

    monkeypatch.setattr(optimizer, "_apply_file_edits_with_validation", fake_apply_file_edits)
    artifact = LogicPortArtifact(
        summary="Candidate fails tests",
        impact="Needs repair.",
        files=[{"path": target_path, "content": "export const repaired = 'bad';\n"}],
        target_task="Task checkbox-1: Port repair runtime feature",
        proposal_transport="worktree",
        dry_run=False,
    )
    context = OptimizationContext(session_id="repair-session", input_data={}, domain="logic-port")

    result = optimizer.optimize(artifact, score=0.0, feedback=[], context=context)

    assert result.applied is True
    assert result.files == [{"path": target_path, "content": "export const repaired = true;\n"}]
    assert result.summary == "Repair validation failure in worktree"
    assert any(state == "repairing_failed_worktree_validation" for state, _details in states)
    codex_call = next(call for call in command_calls if call["command"][0] == "codex-test")
    assert "failed_validation_results" in codex_call["stdin"]
    assert "expected repaired to be true" in codex_call["stdin"]


def test_cleanup_stale_worktrees_sweeps_cycle_and_repair_worktrees(tmp_path, monkeypatch):
    worktree_root = tmp_path / ".daemon" / "logic-port-worktrees"
    cycle = worktree_root / "cycle_01_20260101T000000000000Z_12345"
    repair = worktree_root / "repair_01_20260101T000000000000Z_12345"
    for path in (cycle, repair):
        path.mkdir(parents=True)
        (path / ".logic_port_worktree_owner.json").write_text(
            json.dumps({"pid": 12345, "created_at_epoch": 1}),
            encoding="utf-8",
        )
    calls = []

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        command = tuple(command)
        calls.append(command)
        if command[:3] == ("git", "worktree", "list"):
            return logic_port_daemon.CommandResult(
                command,
                0,
                f"worktree {cycle.resolve()}\nworktree {repair.resolve()}\n",
                "",
            )
        return logic_port_daemon.CommandResult(command, 0, "", "")

    monkeypatch.setattr(logic_port_daemon, "run_command", fake_run_command)
    monkeypatch.setattr(logic_port_daemon, "_pid_looks_like_logic_port_owner", lambda *args, **kwargs: False)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        worktree_root=worktree_root,
        worktree_stale_after_seconds=1,
    )

    result = LogicPortDaemonOptimizer(config).cleanup_stale_worktrees()

    removed_paths = {Path(item["path"]).name for item in result["removed"]}
    assert {"cycle_01_20260101T000000000000Z_12345", "repair_01_20260101T000000000000Z_12345"} <= removed_paths
    assert ("git", "worktree", "remove", "--force", str(cycle.resolve())) in calls
    assert ("git", "worktree", "remove", "--force", str(repair.resolve())) in calls


def test_repair_common_typescript_text_damage_fills_lost_syntax():
    damaged = """
export interface Example {
  metadata: Record;
  values: Array;
  history: Array>;
  lookup: Map;
}
export class Entity {
  addMention(position: number): void {
    if (!Number.isInteger(position) || position  left - right);
  }
}
export class CecDiscourseAnalyzer {
  segments: Array> = [];
  segmentDiscourse(utterances: Array): Array> {
    for (let index = 1; index ): number {
      return index;
    }
  }
}
"""

    repaired = _repair_common_typescript_text_damage(damaged)

    assert "metadata: Record<string, unknown>;" in repaired
    assert "values: Array<unknown>;" in repaired
    assert "history: Array<unknown>;" in repaired
    assert "lookup: Map<string, unknown>;" in repaired
    assert "position < 0" in repaired
    assert "segments: Array<unknown> = [];" in repaired
    assert "segmentDiscourse(utterances: Array<unknown>): Array<unknown>" in repaired
    assert "for (let index = 1; index < utterances.length; index += 1)" in repaired


def test_repair_common_typescript_text_damage_fills_stripped_loop_bounds():
    damaged = """
export function count(input: string): number {
  let total = 0;
  for (let index = 0; index  input.length; index += 1) {
    total += input[index] === "a" ? 1 : 0;
  }
  while (total  input.length) {
    total += 1;
  }
  if (total = input.length || input.length === 0) {
    return total;
  }
  return total;
}
"""

    repaired = _repair_common_typescript_text_damage(damaged)

    assert "for (let index = 0; index < input.length; index += 1)" in repaired
    assert "while (total < input.length)" in repaired
    assert "if (total >= input.length || input.length === 0)" in repaired


def test_repair_common_typescript_text_damage_recovers_string_arrays_and_while_guards():
    damaged = """
const ORDERED_SYMBOLS: Array = Object.keys(SYMBOL_REPLACEMENTS);
const parts: Array = [];

export function scan(input: string): string {
  let firstParen = 0;
  while (firstParen  input.length && input[firstParen] !== "(") {
    firstParen += 1;
  }
  return parts.map((part: string) => part.trim()).join(",") + ORDERED_SYMBOLS[0];
}
"""

    repaired = _repair_common_typescript_text_damage(damaged)

    assert "const ORDERED_SYMBOLS: Array<string> = Object.keys(SYMBOL_REPLACEMENTS);" in repaired
    assert "const parts: Array<string> = [];" in repaired
    assert "while (firstParen < input.length && input[firstParen] !== \"(\")" in repaired


def test_repair_common_typescript_text_damage_recovers_integer_upper_bounds():
    damaged = """
const MAX_ARITY = 64;

export function validateArity(arity: number): boolean {
  return Number.isInteger(arity) && arity >= 0 && !(arity  MAX_ARITY);
}

export function assertArity(arity: number): void {
  if (!Number.isInteger(arity) || arity  MAX_ARITY) {
    throw new Error('bad arity');
  }
}
"""

    repaired = _repair_common_typescript_text_damage(damaged)

    assert "arity > MAX_ARITY" in repaired
    assert "if (!Number.isInteger(arity) || arity > MAX_ARITY)" in repaired


def test_obvious_typescript_text_damage_detects_stripped_operator_artifacts():
    damaged = """
export function validateArity(arity: number): void {
  if (arity  'Entity');
  const metadata: Record = {};
}
"""

    findings = logic_port_daemon._obvious_typescript_text_damage(damaged)

    assert any("missing comparison operator before a string literal" in finding for finding in findings)
    assert any("bare TypeScript generic alias" in finding for finding in findings)


def test_extract_plan_tasks_reads_status_from_markdown():
    tasks = extract_plan_tasks(
        """
### Task 0.1: Add Parser Snapshot Fixtures

Acceptance:
- Snapshot test passes.

### Task 2.1: Add IR-To-Deontic Exporter

Status: implemented for deontic/frame formula generation.

### Task 4.1: Applicability And Exemptions

Status: partially implemented in the current parser.
"""
    )

    assert [(task.task_id, task.title, task.status) for task in tasks] == [
        ("0.1", "Add Parser Snapshot Fixtures", "needed"),
        ("2.1", "Add IR-To-Deontic Exporter", "complete"),
        ("4.1", "Applicability And Exemptions", "in-progress"),
    ]


def test_extract_plan_tasks_reads_port_plan_checkboxes():
    tasks = extract_plan_tasks(
        """
### Phase 13: Browser-Native ML/NLP Parity

- [x] Port `ml_confidence.py` deterministic fallback scoring.
- [ ] Replace spaCy extraction with browser-native NLP.
  - [~] Add local model artifact loading.
- [!] Remove server fallback calls.
"""
    )

    assert [(task.title, task.status) for task in tasks] == [
        ("Port `ml_confidence.py` deterministic fallback scoring.", "complete"),
        ("Replace spaCy extraction with browser-native NLP.", "needed"),
        ("Add local model artifact loading.", "in-progress"),
        ("Remove server fallback calls.", "blocked"),
    ]


def test_daemon_selection_skips_blocked_tasks(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Blocked task\n- [ ] Ready task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Ready task"


def test_daemon_selection_can_revisit_blocked_tasks_when_enabled(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n- [!] Blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        revisit_blocked_tasks=True,
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Blocked task"


def test_revisit_blocked_skips_capability_cleanup_until_ml_nlp_prereqs_are_done(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (logic_dir / "runtimeCapabilities.ts").write_text(
        "export const flags = { nlpUnavailable: true, mlUnavailable: false };\n",
        encoding="utf-8",
    )
    plan.write_text(
        "\n".join(
            [
                "- [x] Complete task",
                "- [!] Replace spaCy extraction with browser-native NLP.",
                "- [!] Remove `nlpUnavailable` and `mlUnavailable` capability flags once browser-native parity is implemented.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Replace spaCy extraction with browser-native NLP."


def test_revisit_blocked_treats_dependent_cleanup_as_no_eligible_task(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (logic_dir / "runtimeCapabilities.ts").write_text(
        "export const flags = { nlpUnavailable: true, mlUnavailable: false };\n",
        encoding="utf-8",
    )
    plan.write_text(
        "- [x] Complete task\n"
        "- [!] Remove `nlpUnavailable` and `mlUnavailable` capability flags once browser-native parity is implemented.\n",
        encoding="utf-8",
    )
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        revisit_blocked_tasks=True,
        replenish_plan_when_empty=False,
    )

    optimizer = LogicPortDaemonOptimizer(config)

    assert optimizer._current_plan_task() is None
    result = optimizer._no_eligible_task_result()
    assert result is not None
    assert result["artifact"]["failure_kind"] == "no_eligible_tasks"


def test_capability_cleanup_dependency_ignores_test_only_markers(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (logic_dir / "runtimeCapabilities.ts").write_text("export const ready = true;\n", encoding="utf-8")
    (logic_dir / "runtimeCapabilities.test.ts").write_text(
        "expect('nlpUnavailable mlUnavailable').toBeTruthy();\n",
        encoding="utf-8",
    )
    plan.write_text(
        "- [x] Replace spaCy extraction with browser-native NLP.\n"
        "- [x] Port `ml_confidence.py` to local browser inference or an equivalent deterministic TypeScript model.\n"
        "- [!] Remove `nlpUnavailable` and `mlUnavailable` capability flags once browser-native parity is implemented.\n",
        encoding="utf-8",
    )
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        revisit_blocked_tasks=True,
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Remove `nlpUnavailable` and `mlUnavailable` capability flags once browser-native parity is implemented."


def test_revisit_blocked_tasks_can_select_fewest_failures(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Hard blocked task\n- [!] Easier blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    hard_rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Hard blocked task",
                "summary": f"hard {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(3)
    ]
    easy_row = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-2: Easier blocked task",
            "summary": "easy",
            "failure_kind": "validation",
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [*hard_rows, easy_row]}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Easier blocked task"


def test_task_board_marks_artifact_target_not_next_strategy_target(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Hard blocked task\n- [!] Easier blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    hard_rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Hard blocked task",
                "summary": f"hard {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(4)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": hard_rows}) + "\n", encoding="utf-8")
    latest = {
        "valid": True,
        "artifact": {
            "target_task": "Task checkbox-1: Hard blocked task",
            "summary": "hard fixed",
            "changed_files": ["src/lib/logic/feature.ts"],
            "validation_results": [],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
    )

    LogicPortDaemonOptimizer(config)._update_task_board([latest])

    updated = plan.read_text(encoding="utf-8")
    assert "- [x] Hard blocked task" in updated
    assert "- [!] Easier blocked task" in updated
    assert "Current target: `Task checkbox-2: Easier blocked task`" in updated
    assert "Target: `Task checkbox-1: Hard blocked task`" in updated


def test_dry_run_daemon_calls_gpt_55_and_does_not_apply_patch(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    patch = "diff --git a/new-file.txt b/new-file.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new-file.txt\n@@ -0,0 +1 @@\n+created\n"
    router = FakeRouter(json.dumps({"summary": "Create file", "patch": patch, "tasks": ["IR"]}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="test-session")

    assert router.calls
    assert router.calls[0]["kwargs"]["model_name"] == "gpt-5.5"
    assert router.calls[0]["kwargs"]["provider"] is None
    assert router.calls[0]["kwargs"]["allow_local_fallback"] is False
    assert router.calls[0]["kwargs"]["max_new_tokens"] == 4096
    assert router.calls[0]["kwargs"]["timeout"] == 300
    assert router.calls[0]["kwargs"]["trace"] is True
    assert router.calls[0]["kwargs"]["trace_dir"].endswith("ipfs_datasets_py/.daemon/codex-runs")
    assert "DETERMINISTIC" not in router.calls[0]["prompt"] or "Port deterministic parser IR" in router.calls[0]["prompt"]
    assert "Do not add Node-only, Rust FFI, filesystem, subprocess, RPC, or server fallbacks" in router.calls[0]["prompt"]
    assert 'For tasks phrased "where feasible"' in router.calls[0]["prompt"]
    assert "Do not run exploratory shell commands in the Codex subprocess" in router.calls[0]["prompt"]
    assert result["valid"] is True
    assert result["artifact"]["has_patch"] is True
    assert not (tmp_path / "new-file.txt").exists()


def test_daemon_can_pin_explicit_llm_router_provider(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    router = FakeRouter(json.dumps({"summary": "Noop", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        provider="codex_cli",
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="explicit-provider")

    assert router.calls[0]["kwargs"]["provider"] == "codex_cli"


def test_daemon_default_llm_call_uses_shared_router_invocation(tmp_path, monkeypatch):
    status_path = tmp_path / "daemon" / "status.json"
    captured = {}

    def fake_call_llm_router(prompt, invocation):
        captured["prompt"] = prompt
        captured["invocation"] = invocation
        return json.dumps({"summary": "Shared call", "patch": ""})

    monkeypatch.setattr(logic_port_daemon, "call_llm_router", fake_call_llm_router)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        status_path=status_path,
        provider="codex_cli",
        model_name="gpt-5.5",
        allow_local_fallback=False,
        llm_timeout_seconds=123,
        max_prompt_chars=4096,
        max_new_tokens=777,
        temperature=0.3,
        codex_trace_dir=Path(".daemon/codex-runs"),
    )

    response = LogicPortDaemonOptimizer(config)._call_llm("return json")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    invocation = captured["invocation"]

    assert response == json.dumps({"summary": "Shared call", "patch": ""})
    assert captured["prompt"] == "return json"
    assert invocation.repo_root == tmp_path
    assert invocation.provider == "codex_cli"
    assert invocation.model_name == "gpt-5.5"
    assert invocation.allow_local_fallback is False
    assert invocation.timeout_seconds == 123
    assert invocation.max_prompt_chars == 4096
    assert invocation.max_new_tokens == 777
    assert invocation.temperature == 0.3
    assert invocation.env_prefix == "LOGIC_PORT_DAEMON_LLM"
    assert invocation.trace is True
    assert invocation.trace_dir == tmp_path / ".daemon" / "codex-runs"
    assert status["state"] == "llm_call_completed"
    assert status["provider"] == "codex_cli"


def test_build_prompt_uses_focused_task_board_excerpt(tmp_path):
    plan = tmp_path / "docs" / "IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    plan.parent.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text(
        "\n".join(
            [
                "# Port Plan",
                "- [x] Already complete",
                *[f"early filler {index}" for index in range(250)],
                "- [ ] Selected browser-native profiler parity",
                *[f"late filler {index}" for index in range(250)],
                "- [ ] Later task marker",
            ]
        ),
        encoding="utf-8",
    )
    status.write_text("status notes\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "Noop", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        validation_commands=tuple(),
        max_prompt_chars=9000,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="focused-prompt")

    prompt = router.calls[0]["prompt"]
    assert len(prompt) <= 9050
    assert "Task checkbox-2: Selected browser-native profiler parity" in prompt
    assert "[task-board excerpt centered on daemon-selected task]" in prompt
    assert "Selected browser-native profiler parity" in prompt
    assert "Later task marker" not in prompt


def test_balanced_slice_mode_keeps_recovery_from_tiny_scaffolds(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    task_label = "Task checkbox-1: Port DCEC wrapper"
    plan.write_text("- [ ] Port DCEC wrapper\n", encoding="utf-8")
    status.write_text("status notes\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True)
    failure = {
        "valid": False,
        "artifact": {
            "target_task": task_label,
            "summary": "bad ts",
            "failure_kind": "typescript_quality",
            "changed_files": [],
            "errors": ["src/lib/logic/cec/dcecWrapper.ts(1,1): error TS1005: ';' expected."],
        },
    }
    log_path.write_text(json.dumps({"results": [failure, failure]}) + "\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "Noop", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        validation_commands=tuple(),
        result_log_path=log_path,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="balanced-slice")

    prompt = router.calls[0]["prompt"]
    assert "Slice mode requested by daemon: balanced" in prompt
    assert "balanced slice mode should still land a useful vertical slice rather than a tiny scaffold" in prompt
    assert "smallest compileable TypeScript contract" not in prompt
    assert "usually 1-3 related implementation/test files" in prompt


def test_consecutive_rollback_failures_enable_unattended_recovery_prompt(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port DCEC cleaning\n", encoding="utf-8")
    status.write_text("status notes\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True)
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Port DCEC cleaning",
                "summary": f"rollback {index}",
                "failure_kind": "preflight",
                "changed_files": [],
                "errors": ["src/lib/logic/cec/dcecCleaning.ts(1,1): error TS1005: ';' expected."],
            },
        }
        for index in range(3)
    ]
    log_path.write_text(json.dumps({"results": rows}) + "\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "Noop", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        validation_commands=tuple(),
        result_log_path=log_path,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="rollback-recovery")

    prompt = router.calls[0]["prompt"]
    assert "Unattended rollback recovery mode is active" in prompt
    assert "Preserve existing exports used by neighboring files" in prompt


def test_small_slice_mode_preserves_minimal_recovery_prompt(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    task_label = "Task checkbox-1: Port DCEC wrapper"
    plan.write_text("- [ ] Port DCEC wrapper\n", encoding="utf-8")
    status.write_text("status notes\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True)
    failure = {
        "valid": False,
        "artifact": {
            "target_task": task_label,
            "summary": "bad ts",
            "failure_kind": "typescript_quality",
            "changed_files": [],
            "errors": ["src/lib/logic/cec/dcecWrapper.ts(1,1): error TS1005: ';' expected."],
        },
    }
    log_path.write_text(json.dumps({"results": [failure, failure]}) + "\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "Noop", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        slice_mode="small",
        dry_run=True,
        validation_commands=tuple(),
        result_log_path=log_path,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="small-slice")

    prompt = router.calls[0]["prompt"]
    assert "Slice mode requested by daemon: small" in prompt
    assert "smallest compileable TypeScript contract" in prompt
    assert "Prefer one implementation file plus one focused test file" in prompt


def test_preflight_repair_recovers_malformed_typescript_files(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port CEC ZKP integration\n", encoding="utf-8")
    status.write_text("status notes\n", encoding="utf-8")

    bad = {
        "summary": "Bad generic",
        "impact": "Adds a malformed replacement that needs preflight repair.",
        "tasks": ["Task checkbox-1: Port CEC ZKP integration"],
        "patch": "",
        "files": [{"path": "src/lib/logic/cecZkpIntegration.ts", "content": "export const bad = ;\n"}],
    }
    fixed = {
        "summary": "Fixed generic",
        "impact": "Adds a compileable replacement after preflight repair.",
        "tasks": ["Task checkbox-1: Port CEC ZKP integration"],
        "patch": "",
        "files": [
            {
                "path": "src/lib/logic/cecZkpIntegration.ts",
                "content": "export type Good = Record<string, unknown>;\n",
            }
        ],
    }
    router = SequencedRouter([json.dumps(bad), json.dumps(fixed)])
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        task_board_doc=plan,
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        validation_commands=tuple(),
        max_iterations=1,
    )
    optimizer = LogicPortDaemonOptimizer(config, llm_router=router)

    def fake_preflight(edits):
        content = "\n".join(edit["content"] for edit in edits)
        if "export const bad = ;" in content:
            return [
                "Rejected proposal because TypeScript replacement preflight found parser or generic/type-quality errors before touching the worktree:\n"
                "src/lib/logic/cecZkpIntegration.ts(1,20): error TS1109: Expression expected."
            ]
        return []

    monkeypatch.setattr(optimizer, "_typescript_replacement_preflight_errors", fake_preflight)

    result = optimizer.run_once(session_id="preflight-repair")

    assert result["valid"] is True
    assert result["artifact"]["summary"] == "Fixed generic"
    assert result["artifact"]["files"] == ["src/lib/logic/cecZkpIntegration.ts"]
    assert len(router.calls) == 2
    assert "preflight rejected them before touching the worktree" in router.calls[1]["prompt"]
    assert "export type Good = Record<string, unknown>;" in router.responses[1]


def test_daemon_reports_router_failures_without_traceback(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
    )

    results = LogicPortDaemonOptimizer(config, llm_router=FailingRouter()).run_daemon()

    assert len(results) == 1
    assert results[0]["valid"] is False
    assert results[0]["artifact"]["errors"] == ["no route"]


def test_supervised_mode_retries_without_user_input(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
        retry_interval_seconds=0,
        max_failure_cycles=2,
    )

    results = LogicPortDaemonOptimizer(config, llm_router=FailingRouter()).run_supervised(cycles=10)

    assert len(results) == 2
    assert all(result["valid"] is False for result in results)


def test_supervised_mode_appends_jsonl_cycle_results(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
        retry_interval_seconds=0,
        max_failure_cycles=1,
        result_log_path=log_path,
    )

    LogicPortDaemonOptimizer(config, llm_router=FailingRouter()).run_supervised(cycles=1)

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["results"][0]["valid"] is False


def test_daemon_updates_markdown_task_board_after_round(tmp_path):
    plan = tmp_path / "implementation.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text(
        "# Plan\n\n"
        "### Task 0.1: Add Parser Snapshot Fixtures\n\n"
        "Acceptance:\n- Snapshot test passes.\n\n"
        "### Task 2.1: Add IR-To-Deontic Exporter\n\n"
        "Status: implemented for deontic/frame formula generation.\n",
        encoding="utf-8",
    )
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    LogicPortDaemonOptimizer(config, llm_router=FakeRouter(json.dumps({"summary": "No safe change", "patch": ""}))).run_daemon()

    updated = plan.read_text(encoding="utf-8")
    assert "## Daemon Task Board" in updated
    assert "Current target: `Task 0.1: Add Parser Snapshot Fixtures`" in updated
    assert "- [!] `Task 0.1: Add Parser Snapshot Fixtures` - latest daemon round failed validation or preflight" in updated
    assert "- [x] `Task 2.1: Add IR-To-Deontic Exporter` - complete" in updated


def test_daemon_marks_valid_checkbox_task_complete_and_reports_changed_files(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = docs_dir / "fixture.md"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [ ] Record accepted work docs\n- [ ] Implement next feature\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Update fixture",
            "files": [{"path": "docs/fixture.md", "content": "new\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="changed-files")
    LogicPortDaemonOptimizer(config)._update_task_board([result])

    updated = plan.read_text(encoding="utf-8")
    assert "- [x] Record accepted work docs" in updated
    assert "Current target: `Task checkbox-2: Implement next feature`" in updated
    assert "- Accepted changed files: `docs/fixture.md`" in updated
    assert result["artifact"]["changed_files"] == ["docs/fixture.md"]


def test_preflight_rejects_non_runtime_only_change_for_implementation_task(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port every TDFOL inference rule\n", encoding="utf-8")
    status.write_text("| TDFOL | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Docs only",
            "files": [{"path": "docs/notes.md", "content": "not enough\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="implementation-guard")

    assert result["valid"] is False
    assert result["artifact"]["changed_files"] == []
    assert not (docs_dir / "notes.md").exists()
    assert "does not change any runtime TypeScript file" in result["artifact"]["errors"][0]


def test_preflight_rejects_fixture_without_test_update(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    parity_dir = logic_dir / "parity"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    parity_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Add Python parity fixtures\n", encoding="utf-8")
    status.write_text("| parity | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Fixture without test",
            "files": [{"path": "src/lib/logic/parity/python-parity-fixtures.json", "content": "[]\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="fixture-guard")

    assert result["valid"] is False
    assert not (parity_dir / "python-parity-fixtures.json").exists()
    assert "must update a src/lib/logic/*.test.ts file" in result["artifact"]["errors"][0]


def test_accepted_work_log_records_valid_changed_files(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "docs" / "accepted.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Runtime feature",
            "impact": "Feature is imported by the logic runtime.",
            "files": [{"path": "src/lib/logic/feature.ts", "content": "new\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        accepted_work_log_path=log_path,
        accepted_work_artifact_dir=tmp_path / "artifacts",
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="accepted-log")
    LogicPortDaemonOptimizer(config)._append_accepted_work_log([result])

    accepted = log_path.read_text(encoding="utf-8")
    assert "Runtime feature" in accepted
    assert "`src/lib/logic/feature.ts`" in accepted
    assert "Feature is imported by the logic runtime." in accepted
    assert "Evidence:" in accepted
    artifact_files = list((tmp_path / "artifacts").glob("*"))
    assert any(path.suffix == ".json" for path in artifact_files)
    assert any(path.suffix == ".diff" for path in artifact_files)
    assert not any(path.suffix == ".patch" for path in artifact_files)
    assert any(path.name.endswith(".stat.txt") for path in artifact_files)


def test_auto_commit_after_valid_round_commits_daemon_scope(tmp_path):
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan = docs_dir / "port-plan.md"
    status = docs_dir / "status.md"
    accepted = docs_dir / "accepted.md"
    feature = logic_dir / "feature.ts"
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    feature.write_text("export const feature = 'old';\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    response = json.dumps(
        {
            "summary": "Runtime feature",
            "impact": "Feature is imported by the logic runtime.",
            "files": [{"path": "src/lib/logic/feature.ts", "content": "export const feature = 'new';\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        accepted_work_log_path=accepted,
        accepted_work_artifact_dir=None,
        auto_commit=True,
        auto_commit_branch="main",
    )

    results = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_daemon()

    assert results[-1]["valid"] is True
    assert results[-1]["artifact"]["auto_commit"]["committed"] is True
    status_result = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/lib/logic", "docs/port-plan.md", "docs/accepted.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status_result.stdout == ""
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject.startswith("chore(logic-port):")


def test_startup_dirty_auto_commit_commits_existing_daemon_scope(tmp_path):
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan = docs_dir / "port-plan.md"
    accepted = docs_dir / "accepted.md"
    feature = logic_dir / "feature.ts"
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    accepted.write_text("# Accepted\n", encoding="utf-8")
    feature.write_text("export const feature = 'old';\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    plan.write_text("- [x] Port runtime feature\n", encoding="utf-8")
    feature.write_text("export const feature = 'dirty';\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(accepted,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        validation_commands=tuple(),
        task_board_doc=plan,
        accepted_work_log_path=accepted,
        auto_commit=True,
        auto_commit_branch="main",
        auto_commit_startup_dirty=True,
    )

    LogicPortDaemonOptimizer(config)._auto_commit_startup_dirty_scope()

    status_result = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/lib/logic", "docs/port-plan.md", "docs/accepted.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status_result.stdout == ""
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject.startswith("chore(logic-port):")


def test_file_edit_mode_rejects_noop_file_replacements(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = docs_dir / "fixture.md"
    target.write_text("same\n", encoding="utf-8")
    plan.write_text("- [ ] Record accepted work docs\n", encoding="utf-8")
    status.write_text("| docs | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "No-op docs",
            "files": [{"path": "docs/fixture.md", "content": "same\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="noop")

    assert result["valid"] is False
    assert result["artifact"]["changed_files"] == []
    assert "made no content changes" in result["artifact"]["errors"][0]


def test_malformed_patch_falls_back_to_complete_file_replacements(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("export const value = 'old';\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    malformed_patch = (
        "diff --git a/src/lib/logic/feature.ts b/src/lib/logic/feature.ts\n"
        "--- a/src/lib/logic/feature.ts\n"
        "+++ b/src/lib/logic/feature.ts\n"
        "@@ broken hunk header\n"
        "-export const value = 'old';\n"
        "+export const value = 'new';\n"
    )
    repair_response = json.dumps(
        {
            "summary": "Repair as file replacement",
            "impact": "Runtime feature is updated by a complete file replacement.",
            "patch": "",
            "files": [{"path": "src/lib/logic/feature.ts", "content": "export const value = 'new';\n"}],
        }
    )
    router = SequencedRouter(
        [
            json.dumps({"summary": "Malformed runtime patch", "patch": malformed_patch}),
            json.dumps({"summary": "Still malformed", "patch": malformed_patch}),
            repair_response,
        ]
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="file-repair")

    assert result["valid"] is True
    assert target.read_text(encoding="utf-8") == 'export const value = "new";\n'
    assert result["artifact"]["files"] == ["src/lib/logic/feature.ts"]
    assert result["artifact"]["changed_files"] == ["src/lib/logic/feature.ts"]
    assert len(router.calls) == 3
    assert "runtime TypeScript changes must use JSON `files` complete replacements" in router.calls[1]["prompt"]


def test_status_file_records_liveness_and_latest_artifact(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    status_path = tmp_path / "daemon" / "status.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Runtime feature",
            "files": [{"path": "src/lib/logic/feature.ts", "content": "new\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        status_path=status_path,
    )

    LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_supervised(cycles=1)

    heartbeat = json.loads(status_path.read_text(encoding="utf-8"))
    assert heartbeat["state"] == "cycle_completed"
    assert heartbeat["valid"] is True
    assert heartbeat["artifact"]["summary"] == "Runtime feature"
    assert heartbeat["artifact"]["valid_changed_files"] == ["src/lib/logic/feature.ts"]


def test_status_file_preserves_phase_start_for_stuck_detection(tmp_path):
    status_path = tmp_path / "daemon" / "status.json"
    config = LogicPortDaemonConfig(repo_root=tmp_path, status_path=status_path)
    optimizer = LogicPortDaemonOptimizer(config, llm_router=FakeRouter("{}"))

    optimizer._write_status("llm_call_started", timeout_seconds=300, prompt_chars=100)
    first = json.loads(status_path.read_text(encoding="utf-8"))
    optimizer._write_status("llm_call_started", timeout_seconds=300, prompt_chars=200)
    second = json.loads(status_path.read_text(encoding="utf-8"))
    optimizer._write_status("llm_call_completed", response_chars=10)
    completed = json.loads(status_path.read_text(encoding="utf-8"))

    assert first["state"] == "llm_call_started"
    assert first["state_started_at"] == first["timestamp"]
    assert first["heartbeat_at"] == first["timestamp"]
    assert first["updated_at"] == first["timestamp"]
    assert second["state"] == "llm_call_started"
    assert second["state_started_at"] == first["state_started_at"]
    assert completed["state"] == "llm_call_completed"
    assert completed["state_started_at"] == completed["timestamp"]


def test_llm_call_has_daemon_side_deadline_for_stuck_router(tmp_path):
    status_path = tmp_path / "daemon" / "status.json"
    router = HangingRouter()
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        status_path=status_path,
        llm_timeout_seconds=0.01,
    )
    optimizer = LogicPortDaemonOptimizer(config, llm_router=router)

    try:
        optimizer._call_llm("return json")
    except TimeoutError as exc:
        assert "exceeded daemon deadline" in str(exc)
    else:
        raise AssertionError("Expected stuck router call to time out")

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert router.calls
    assert router.calls[0]["kwargs"]["timeout"] == 0.01
    assert router.calls[0]["kwargs"]["provider"] is None
    assert status["state"] == "llm_call_timeout"
    assert status["provider"] == "auto"
    assert status["timeout_seconds"] == 0.01
    assert status["state_started_at"] == status["timestamp"]


def test_daemon_retries_empty_or_non_json_proposals_as_file_replacements(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    router = SequencedRouter(
        [
            "I cannot edit files in a read-only sandbox.",
            json.dumps({"summary": "empty", "patch": "", "files": []}),
            json.dumps(
                {
                    "summary": "Runtime feature",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "new\n"}],
                }
            ),
        ]
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        proposal_attempts=3,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="proposal-retry")

    assert result["valid"] is True
    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(router.calls) == 3
    assert "Do not refuse because of a read-only sandbox" in router.calls[1]["prompt"]


def test_runtime_typescript_patch_is_retried_as_file_replacement(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("export const value = 'old';\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    patch = (
        "diff --git a/src/lib/logic/feature.ts b/src/lib/logic/feature.ts\n"
        "--- a/src/lib/logic/feature.ts\n"
        "+++ b/src/lib/logic/feature.ts\n"
        "@@ -1 +1 @@\n"
        "-export const value = 'old';\n"
        "+export const value = 'patch';\n"
    )
    router = SequencedRouter(
        [
            json.dumps({"summary": "Patch runtime feature", "patch": patch, "files": []}),
            json.dumps(
                {
                    "summary": "File runtime feature",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "export const value = 'file';\n"}],
                }
            ),
        ]
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        proposal_attempts=2,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="runtime-patch-retry")

    assert result["valid"] is True
    assert target.read_text(encoding="utf-8") == 'export const value = "file";\n'
    assert len(router.calls) == 2
    assert "runtime TypeScript changes must use JSON `files` complete replacements" in router.calls[1]["prompt"]


def test_empty_proposal_gets_failure_kind_for_task_blocking(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        proposal_attempts=1,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(json.dumps({"summary": "empty", "patch": "", "files": []}))).run_once(
        session_id="empty-proposal"
    )

    assert result["valid"] is False
    assert result["artifact"]["failure_kind"] == "empty_proposal"
    assert "No usable patch or file replacement" in result["artifact"]["errors"][0]


def test_prompt_includes_relevant_file_contents_and_recent_failures(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    cec_dir = logic_dir / "cec"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    cec_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (cec_dir / "problemParser.ts").write_text("export const currentProblemParser = true;\n", encoding="utf-8")
    (cec_dir / "problemParser.test.ts").write_text("describe('problem parser', () => {});\n", encoding="utf-8")
    plan.write_text("- [ ] Port CEC problem parser\n", encoding="utf-8")
    status.write_text("| cec | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Port CEC problem parser",
            "summary": "bad parser",
            "failure_kind": "validation",
            "errors": ["File edits failed validation and were rolled back."],
            "validation_results": [
                {
                    "command": ["npx", "tsc", "--noEmit"],
                    "returncode": 2,
                    "stdout": "src/lib/logic/cec/problemParser.ts(10,1): error TS1005: ';' expected.\n",
                    "stderr": "",
                }
            ],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    subprocess.run(("git", "init"), cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    response = json.dumps({"summary": "empty", "patch": "", "files": []})
    router = FakeRouter(response)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        max_iterations=1,
        validation_commands=tuple(),
        task_board_doc=plan,
        result_log_path=log_path,
        proposal_attempts=1,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="context-prompt")

    prompt = router.calls[0]["prompt"]
    assert "Recent daemon failures for the selected task" in prompt
    assert "TS1005" in prompt
    assert "currentProblemParser" in prompt
    assert "src/lib/logic/cec/problemParser.ts" in prompt


def test_file_edit_validation_failure_gets_repaired_before_round_fails(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")

    router = SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "Bad runtime feature",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "bad\n"}],
                }
            ),
            json.dumps(
                {
                    "summary": "Repaired runtime feature",
                    "impact": "The corrected runtime file passes validation.",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "good\n"}],
                }
            ),
        ]
    )
    validation = (
        "python3",
        "-c",
        "from pathlib import Path; import sys; text=Path('src/lib/logic/feature.ts').read_text(); sys.exit(1 if 'bad' in text else 0)",
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=(validation,),
        task_board_doc=plan,
        proposal_attempts=1,
        validation_repair_attempts=1,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="validation-repair")

    assert result["valid"] is True
    assert target.read_text(encoding="utf-8") == "good;\n"
    assert result["artifact"]["summary"] == "Repaired runtime feature"
    assert result["artifact"]["changed_files"] == ["src/lib/logic/feature.ts"]
    assert len(router.calls) == 2
    assert "validation failed and the edits were rolled back" in router.calls[1]["prompt"]


def test_progress_summary_records_acceptance_rate_and_current_task(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    progress_path = tmp_path / "daemon" / "progress.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Done task\n- [ ] Next task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps(
            {
                "pid": 1,
                "results": [
                    {
                        "valid": True,
                        "score": 1.0,
                        "artifact": {
                            "target_task": "Task checkbox-1: Done task",
                            "summary": "accepted",
                            "changed_files": ["src/lib/logic/done.ts"],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    latest = {
        "valid": False,
        "score": 0.0,
        "artifact": {
            "target_task": "Task checkbox-2: Next task",
            "summary": "failed",
            "failure_kind": "",
            "changed_files": [],
            "errors": ["403 Forbidden <html><body>very long cloudflare challenge</body></html>"],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        result_log_path=log_path,
        progress_path=progress_path,
        task_board_doc=plan,
    )

    LogicPortDaemonOptimizer(config)._write_progress_summary(
        cycle_results=[latest],
        completed_cycles=2,
        consecutive_failure_cycles=1,
        active_state="cycle_failed",
    )

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["rounds_total"] == 2
    assert progress["active_state"] == "cycle_failed"
    assert progress["valid_rounds_total"] == 1
    assert progress["stagnant_rounds_since_valid"] == 1
    assert progress["current_task"] == "Task checkbox-2: Next task"
    assert progress["current_task_failure_counts"]["total_since_success"] == 1
    assert progress["latest_round"]["failure_kind"] == "provider_http_403"
    assert progress["failure_kind_counts"]["provider_http_403"] == 1
    assert "[html response omitted]" in progress["latest_round"]["errors"][0]
    assert progress["recent_valid_rounds"][0]["changed_files"] == ["src/lib/logic/done.ts"]


def test_task_board_blocks_repeated_same_failure_kind(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Add stubborn fixture\n- [ ] Next task\n", encoding="utf-8")
    status.write_text("| parity | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Add stubborn fixture",
            "summary": "failed",
            "failure_kind": "apply_check",
            "errors": ["Patch failed git apply --check."],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    latest = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Add stubborn fixture",
            "summary": "failed again",
            "failure_kind": "apply_check",
            "errors": ["Patch failed git apply --check."],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        max_task_failure_rounds=2,
    )

    LogicPortDaemonOptimizer(config)._update_task_board([latest])

    updated = plan.read_text(encoding="utf-8")
    assert "- [!] Add stubborn fixture" in updated
    assert "Failure kind: `apply_check`" in updated


def test_task_board_blocks_repeated_invalid_rounds_without_failure_kind(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Stuck implementation task\n- [ ] Next task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Stuck implementation task",
            "summary": "empty",
            "failure_kind": "",
            "changed_files": [],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    latest = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Stuck implementation task",
            "summary": "empty again",
            "failure_kind": "",
            "changed_files": [],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        max_task_failure_rounds=2,
    )

    LogicPortDaemonOptimizer(config)._update_task_board([latest])

    updated = plan.read_text(encoding="utf-8")
    assert "- [!] Stuck implementation task" in updated


def test_task_board_blocks_after_total_failures_across_kinds(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Mixed failure task\n- [ ] Next task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = []
    for kind in ("parse", "validation"):
        rows.append(
            {
                "valid": False,
                "artifact": {
                    "target_task": "Task checkbox-1: Mixed failure task",
                    "summary": kind,
                    "failure_kind": kind,
                    "changed_files": [],
                },
            }
        )
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    latest = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Mixed failure task",
            "summary": "apply failed",
            "failure_kind": "apply_check",
            "changed_files": [],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        max_task_failure_rounds=10,
        max_task_total_failure_rounds=3,
    )

    LogicPortDaemonOptimizer(config)._update_task_board([latest])

    updated = plan.read_text(encoding="utf-8")
    assert "- [!] Mixed failure task" in updated


def test_task_board_blocks_repeated_classified_typescript_quality_across_raw_kinds(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Malformed TypeScript task\n- [ ] Next task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Malformed TypeScript task",
            "summary": "validation repair failed",
            "failure_kind": "validation_repair",
            "changed_files": [],
            "validation_results": [
                {
                    "command": ["npx", "tsc", "--noEmit"],
                    "returncode": 2,
                    "stdout": "src/lib/logic/example.ts(1,8): error TS2314: Generic type 'Record' requires 2 type argument(s).\n",
                    "stderr": "",
                }
            ],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    latest = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-1: Malformed TypeScript task",
            "summary": "preflight failed",
            "failure_kind": "preflight",
            "changed_files": [],
            "errors": ["src/lib/logic/example.ts(2,10): error TS1005: ';' expected."],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        max_task_failure_rounds=2,
        max_task_total_failure_rounds=10,
    )

    LogicPortDaemonOptimizer(config)._update_task_board([latest])

    updated = plan.read_text(encoding="utf-8")
    assert "- [!] Malformed TypeScript task" in updated
    assert "Failure kind: `typescript_quality`" in updated


def test_supervised_blocks_stale_failed_task_before_llm_call(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    status_path = tmp_path / "daemon" / "status.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Stale failed task\n- [ ] Fresh task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Stale failed task",
                "summary": f"failed {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(2)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        status_path=status_path,
        max_task_total_failure_rounds=2,
    )

    blocked = LogicPortDaemonOptimizer(config, llm_router=FailingRouter())._block_current_task_if_stale_failed()

    updated = plan.read_text(encoding="utf-8")
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert blocked is True
    assert "- [!] Stale failed task" in updated
    assert "Current target: `Task checkbox-2: Fresh task`" in updated
    assert status_payload["state"] == "task_blocked_before_cycle"


def test_supervised_blocks_stale_task_after_same_kind_failures_before_llm_call(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    status_path = tmp_path / "daemon" / "status.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Repeated malformed task\n- [ ] Fresh task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Repeated malformed task",
                "summary": f"failed {index}",
                "failure_kind": "preflight",
                "changed_files": [],
                "errors": ["src/lib/logic/example.ts(1,8): error TS1005: ';' expected."],
            },
        }
        for index in range(3)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        status_path=status_path,
        max_task_failure_rounds=3,
        max_task_total_failure_rounds=6,
    )

    blocked = LogicPortDaemonOptimizer(config, llm_router=FailingRouter())._block_current_task_if_stale_failed()

    updated = plan.read_text(encoding="utf-8")
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert blocked is True
    assert "- [!] Repeated malformed task" in updated
    assert "Current target: `Task checkbox-2: Fresh task`" in updated
    assert status_payload["state"] == "task_blocked_before_cycle"


def test_daemon_stops_without_llm_when_no_eligible_tasks_remain(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    status_path = tmp_path / "daemon" / "status.json"
    progress_path = tmp_path / "daemon" / "progress.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n- [!] Blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "should not be called", "patch": ""}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        status_path=status_path,
        progress_path=progress_path,
        replenish_plan_when_empty=False,
    )

    results = LogicPortDaemonOptimizer(config, llm_router=router).run_supervised(cycles=0)

    assert len(results) == 1
    assert results[0]["valid"] is True
    assert results[0]["metadata"]["terminal_reason"] == "no_eligible_tasks"
    assert results[0]["artifact"]["failure_kind"] == "no_eligible_tasks"
    assert router.calls == []
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    log_rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert status_payload["state"] == "no_eligible_tasks"
    assert progress_payload["active_state"] == "no_eligible_tasks"
    assert progress_payload["rounds_total"] == 0
    assert progress_payload["valid_rounds_total"] == 0
    assert progress_payload["terminal_events_total"] == 1
    assert progress_payload["plan_status_counts"] == {"complete": 1, "blocked": 1}
    assert log_rows[0]["results"][0]["metadata"]["terminal_reason"] == "no_eligible_tasks"


def test_supervised_revisit_blocked_tasks_calls_llm_instead_of_terminal_stop(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    plan.write_text("- [x] Complete task\n- [!] Blocked runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    router = FakeRouter(
        json.dumps(
            {
                "summary": "Revisit blocked runtime feature",
                "patch": "",
                "files": [{"path": "src/lib/logic/feature.ts", "content": "new\n"}],
            }
        )
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        validation_commands=tuple(),
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
    )

    results = LogicPortDaemonOptimizer(config, llm_router=router).run_supervised(cycles=1)

    assert len(results) == 1
    assert results[0]["valid"] is True
    assert router.calls
    assert "Task checkbox-2: Blocked runtime feature" in router.calls[0]["prompt"]
    assert target.read_text(encoding="utf-8") == "new\n"
    assert "- [x] Blocked runtime feature" in plan.read_text(encoding="utf-8")


def test_revisit_blocked_prompt_includes_blocked_backlog_context(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n- [!] Blocked runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-2: Blocked runtime feature",
            "summary": "bad blocked attempt",
            "failure_kind": "validation",
            "errors": ["src/lib/logic/feature.ts(1,1): error TS1005"],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "empty", "patch": "", "files": []}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=True,
        validation_commands=tuple(),
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        proposal_attempts=1,
    )

    LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="blocked-context")

    prompt = router.calls[0]["prompt"]
    assert "Blocked backlog context" in prompt
    assert "Task checkbox-2: Blocked runtime feature" in prompt
    assert "TS1005" in prompt
    assert "failure kinds" in prompt


def test_task_board_includes_blocked_backlog_failure_evidence(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n- [!] Blocked runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    previous = {
        "valid": False,
        "artifact": {
            "target_task": "Task checkbox-2: Blocked runtime feature",
            "summary": "bad blocked attempt",
            "failure_kind": "validation",
            "errors": ["validation failed"],
        },
    }
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": [previous]}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
    )

    LogicPortDaemonOptimizer(config)._update_task_board([])

    updated = plan.read_text(encoding="utf-8")
    assert "### Blocked Backlog" in updated
    assert "Task checkbox-2: Blocked runtime feature" in updated
    assert "Latest failure kind: `validation`" in updated
    assert "Latest errors: validation failed" in updated


def test_task_board_notes_blocked_task_selection_strategy(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Hard blocked task\n- [!] Easier blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Hard blocked task",
                "summary": f"hard {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(4)
    ]
    rows.append(
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-2: Easier blocked task",
                "summary": "easy",
                "failure_kind": "validation",
            },
        }
    )
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
    )

    LogicPortDaemonOptimizer(config)._update_task_board([])

    updated = plan.read_text(encoding="utf-8")
    assert "with `fewest-failures` strategy" in updated
    assert "Current target: `Task checkbox-2: Easier blocked task`" in updated


def test_run_daemon_stops_without_llm_when_no_eligible_tasks_remain(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n", encoding="utf-8")
    status.write_text("| runtime | complete |\n", encoding="utf-8")
    router = FakeRouter(json.dumps({"summary": "should not be called", "patch": ""}))
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        validation_commands=tuple(),
    )

    results = LogicPortDaemonOptimizer(config, llm_router=router).run_daemon()

    assert len(results) == 1
    assert results[0]["metadata"]["terminal_reason"] == "no_eligible_tasks"
    assert router.calls == []
    assert "Current target: `none`" in plan.read_text(encoding="utf-8")


def test_plan_replenishment_adds_missing_python_logic_tasks(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (python_logic_dir / "unported_feature.py").write_text("class UnportedFeature: pass\n", encoding="utf-8")
    plan.write_text("- [x] Existing complete task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        plan_replenishment_limit=1,
    )

    added = LogicPortDaemonOptimizer(config)._replenish_plan_from_code_state()

    updated = plan.read_text(encoding="utf-8")
    assert added == [
        "Port remaining Python logic module `logic/unported_feature.py` to browser-native TypeScript/WASM, including focused validation tests and no server or Python runtime dependency."
    ]
    assert "## Daemon-Discovered Implementation Gaps" in updated
    assert "- [ ] Port remaining Python logic module `logic/unported_feature.py`" in updated
    assert "Current target: `Task checkbox-2: Port remaining Python logic module 'logic/unported_feature.py' to browser-native TypeScript/WASM, including focused validation tests and no server or Python runtime dependency.`" in updated


def test_plan_replenishment_reviews_original_goal_when_inventory_gaps_are_exhausted(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    (python_logic_dir / "feature.py").write_text("class Feature: pass\n", encoding="utf-8")
    (logic_dir / "feature.ts").write_text("export class Feature {}\n", encoding="utf-8")
    plan.write_text("- [x] Existing complete task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        task_board_doc=plan,
        plan_replenishment_limit=3,
    )

    added = LogicPortDaemonOptimizer(config)._replenish_plan_from_code_state()

    updated = plan.read_text(encoding="utf-8")
    assert len(added) == 3
    assert "accepted-work parity evidence" in added[0]
    assert "original browser-native TypeScript/WASM port goal" in updated
    assert "Python, spaCy, or server-side calls" in updated
    assert "Current target: `Task checkbox-2: Create accepted-work parity evidence" in updated


def test_supervised_replenishes_empty_plan_and_keeps_running(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("old\n", encoding="utf-8")
    (python_logic_dir / "feature_gap.py").write_text("class FeatureGap: pass\n", encoding="utf-8")
    plan.write_text("- [x] Existing complete task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    router = FakeRouter(
        json.dumps(
            {
                "summary": "Port replenished feature",
                "patch": "",
                "files": [{"path": "src/lib/logic/feature.ts", "content": "new\n"}],
            }
        )
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        validation_commands=tuple(),
        task_board_doc=plan,
        result_log_path=log_path,
        plan_replenishment_limit=1,
    )

    results = LogicPortDaemonOptimizer(config, llm_router=router).run_supervised(cycles=1)

    assert len(results) == 1
    assert results[0]["valid"] is True
    assert router.calls
    assert "feature_gap.py" in router.calls[0]["prompt"]
    assert target.read_text(encoding="utf-8") == "new\n"


def test_generate_retries_file_replacement_after_typescript_replacement_preflight(tmp_path, monkeypatch):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("export const value = 'old';\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    router = SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "bad syntax",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "export const value = ;\n"}],
                }
            ),
            json.dumps(
                {
                    "summary": "fixed syntax",
                    "patch": "",
                    "files": [{"path": "src/lib/logic/feature.ts", "content": "export const value = 'new';\n"}],
                }
            ),
        ]
    )

    def fake_syntax_preflight(self, edits):
        content = "\n".join(str(edit.get("content", "")) for edit in edits)
        if "value = ;" in content:
            return [
                "Rejected proposal because TypeScript replacement preflight found parser or generic/type-quality errors before touching the worktree:\n"
                "src/lib/logic/feature.ts(1,22): error TS1005: Expression expected."
            ]
        return []

    monkeypatch.setattr(logic_port_daemon.LogicPortDaemonOptimizer, "_typescript_replacement_preflight_errors", fake_syntax_preflight)
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        validation_commands=tuple(),
        task_board_doc=plan,
        proposal_attempts=2,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="syntax-preflight")

    assert result["valid"] is True
    assert len(router.calls) == 2
    assert "TypeScript replacement preflight" in router.calls[1]["prompt"]
    assert "typescript_diagnostic_context=" in router.calls[1]["prompt"]
    assert "Record<string, unknown>" in router.calls[0]["prompt"]
    assert "Promise<ResultType>" in router.calls[1]["prompt"]
    assert "> 1: export const value = ;" in router.calls[1]["prompt"]
    assert target.read_text(encoding="utf-8") == 'export const value = "new";\n'


def test_typescript_replacement_preflight_rejects_missing_generic_arguments(tmp_path):
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    config = LogicPortDaemonConfig(
        repo_root=Path.cwd(),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        validation_commands=tuple(),
    )

    errors = LogicPortDaemonOptimizer(config)._typescript_replacement_preflight_errors(
        [{"path": "src/lib/logic/example.ts", "content": "export const value: Record = {};\n"}]
    )

    assert errors
    assert "TS2314" in errors[0]


def test_exhausted_preflight_attempts_do_not_apply_bad_replacement(tmp_path, monkeypatch):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    target = logic_dir / "feature.ts"
    target.write_text("export const value = 'old';\n", encoding="utf-8")
    plan.write_text("- [ ] Port runtime feature\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    router = FakeRouter(
        json.dumps(
            {
                "summary": "bad syntax",
                "patch": "",
                "files": [{"path": "src/lib/logic/feature.ts", "content": "export const value = ;\n"}],
            }
        )
    )

    monkeypatch.setattr(
        logic_port_daemon.LogicPortDaemonOptimizer,
        "_typescript_replacement_preflight_errors",
        lambda self, edits: ["Rejected proposal because TypeScript replacement preflight found parser or generic/type-quality errors before touching the worktree."],
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        validation_commands=(("python3", "-c", "raise SystemExit(99)"),),
        task_board_doc=plan,
        proposal_attempts=1,
    )

    result = LogicPortDaemonOptimizer(config, llm_router=router).run_once(session_id="preflight-exhausted")

    assert result["artifact"]["failure_kind"] == "preflight"
    assert result["artifact"]["validation_results"] == []
    assert target.read_text(encoding="utf-8") == "export const value = 'old';\n"


def test_file_edit_mode_applies_allowed_files_and_rolls_back_on_validation_failure(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    docs_dir = tmp_path / "docs"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    docs_dir.mkdir(parents=True)
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")
    target = docs_dir / "example.md"
    target.write_text("old\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Edit docs",
            "tasks": ["small file edit"],
            "files": [{"path": "docs/example.md", "content": "new\n"}],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=(("python3", "-c", "import sys; sys.exit(1)"),),
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="file-edit")

    assert result["valid"] is False
    assert target.read_text(encoding="utf-8") == "old\n"
    assert result["artifact"]["files"] == ["docs/example.md"]


def test_file_edit_mode_rejects_vitest_imports_before_writing(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    response = json.dumps(
        {
            "summary": "Bad test harness",
            "files": [
                {
                    "path": "src/lib/logic/example.test.ts",
                    "content": "import { describe, expect, it } from 'vitest';\n",
                }
            ],
        }
    )
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=tuple(),
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="bad-test-harness")

    assert result["valid"] is False
    assert not (logic_dir / "example.test.ts").exists()
    assert "imports from 'vitest'" in result["artifact"]["errors"][0]


def test_patch_mode_rolls_back_when_validation_fails(tmp_path):
    plan = tmp_path / "plan.md"
    status = tmp_path / "status.md"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port deterministic parser IR\n", encoding="utf-8")
    status.write_text("| ZKP | partial |\n", encoding="utf-8")

    patch = (
        "diff --git a/generated.txt b/generated.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/generated.txt\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
    )
    response = json.dumps({"summary": "Create file", "patch": patch, "tasks": ["rollback"]})
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        max_iterations=1,
        validation_commands=(("python3", "-c", "import sys; sys.exit(1)"),),
    )

    result = LogicPortDaemonOptimizer(config, llm_router=FakeRouter(response)).run_once(session_id="patch-rollback")

    assert result["valid"] is False
    assert result["artifact"]["applied"] is False
    assert not (tmp_path / "generated.txt").exists()
    assert "Patch failed validation and was rolled back." in result["artifact"]["errors"]

def test_revisit_blocked_fewest_failures_rotates_equal_failure_tasks(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] First blocked task\n- [!] Second blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: First blocked task",
                "summary": "first failed",
                "failure_kind": "validation",
            },
        },
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-2: Second blocked task",
                "summary": "second failed more recently",
                "failure_kind": "validation",
            },
        },
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "First blocked task"

def test_revisit_blocked_skips_tasks_after_failure_budget(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Exhausted blocked task\n- [!] Fresh blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Exhausted blocked task",
                "summary": f"failed {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(6)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
        max_task_total_failure_rounds=6,
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()

    assert selected is not None
    assert selected.title == "Fresh blocked task"


def test_revisit_blocked_skips_tasks_after_same_kind_failure_budget(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [!] Repeated bad TypeScript task\n- [!] Fresh blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-1: Repeated bad TypeScript task",
                "summary": f"failed {index}",
                "failure_kind": "preflight",
                "changed_files": [],
                "errors": ["src/lib/logic/example.ts(1,8): error TS2314: Generic type 'Record' requires 2 type argument(s)."],
            },
        }
        for index in range(3)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        blocked_task_strategy="fewest-failures",
        max_task_failure_rounds=3,
        max_task_total_failure_rounds=6,
    )

    selected = LogicPortDaemonOptimizer(config)._current_plan_task()
    backlog = LogicPortDaemonOptimizer(config)._blocked_task_backlog(
        LogicPortDaemonOptimizer(config)._current_plan_tasks(),
        logic_port_daemon._read_daemon_results(log_path),
    )

    assert selected is not None
    assert selected.title == "Fresh blocked task"
    assert backlog[0]["failure_budget_exhausted"] is True


def test_task_failure_counts_normalize_markdown_backticks():
    rows = [
        (
            {"valid": False},
            {
                "target_task": "Task checkbox-203: Port remaining Python logic module logic/CEC/native/dcec_cleaning.py to browser-native TypeScript/WASM",
                "failure_kind": "preflight",
            },
        )
    ]
    task_label = (
        "Task checkbox-203: Port remaining Python logic module `logic/CEC/native/dcec_cleaning.py` "
        "to browser-native TypeScript/WASM"
    )

    assert logic_port_daemon._recent_total_failure_count(rows, task_label) == 1
    assert logic_port_daemon._recent_failure_count(rows, task_label, "preflight") == 1
    assert logic_port_daemon._current_task_failure_counts(rows, task_label)["by_kind_since_success"]["preflight"] == 1


def test_revisit_blocked_stops_when_all_blocked_tasks_exhaust_failure_budget(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [x] Complete task\n- [!] Exhausted blocked task\n", encoding="utf-8")
    status.write_text("| runtime | partial |\n", encoding="utf-8")
    rows = [
        {
            "valid": False,
            "artifact": {
                "target_task": "Task checkbox-2: Exhausted blocked task",
                "summary": f"failed {index}",
                "failure_kind": "validation",
            },
        }
        for index in range(6)
    ]
    log_path.parent.mkdir(parents=True)
    log_path.write_text(json.dumps({"pid": 1, "results": rows}) + "\n", encoding="utf-8")
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
        result_log_path=log_path,
        revisit_blocked_tasks=True,
        replenish_plan_when_empty=False,
        max_task_total_failure_rounds=6,
    )
    optimizer = LogicPortDaemonOptimizer(config)

    assert optimizer._current_plan_task() is None
    result = optimizer._no_eligible_task_result()
    assert result is not None
    assert result["artifact"]["failure_kind"] == "no_eligible_tasks"
    backlog = optimizer._blocked_task_backlog(optimizer._current_plan_tasks(), logic_port_daemon._read_daemon_results(log_path))
    assert backlog[0]["failure_budget_exhausted"] is True

def test_progress_summary_classifies_typescript_quality_failures(tmp_path):
    plan = tmp_path / "port-plan.md"
    status = tmp_path / "status.md"
    log_path = tmp_path / "daemon" / "results.jsonl"
    progress_path = tmp_path / "daemon" / "progress.json"
    logic_dir = tmp_path / "src" / "lib" / "logic"
    python_logic_dir = tmp_path / "ipfs_datasets_py" / "ipfs_datasets_py" / "logic"
    logic_dir.mkdir(parents=True)
    python_logic_dir.mkdir(parents=True)
    plan.write_text("- [ ] Port DCEC wrapper\n", encoding="utf-8")
    status.write_text("| cec | partial |\n", encoding="utf-8")
    latest = {
        "valid": False,
        "score": 0.0,
        "artifact": {
            "target_task": "Task checkbox-1: Port DCEC wrapper",
            "summary": "bad repair",
            "failure_kind": "validation_repair",
            "changed_files": [],
            "errors": ["File edits failed validation and were rolled back."],
            "validation_results": [
                {
                    "command": ["npx", "tsc", "--noEmit"],
                    "returncode": 2,
                    "stdout": (
                        "src/lib/logic/cec/dcecWrapper.ts(8,35): error TS2314: Generic type 'Record' requires 2 type argument(s).\n"
                        "src/lib/logic/cec/dcecWrapper.ts(91,43): error TS2345: Argument of type 'DcecFormula' is not assignable.\n"
                    ),
                    "stderr": "",
                }
            ],
        },
    }
    config = LogicPortDaemonConfig(
        repo_root=tmp_path,
        plan_docs=(plan,),
        status_docs=(status,),
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        dry_run=False,
        result_log_path=log_path,
        progress_path=progress_path,
        task_board_doc=plan,
    )

    LogicPortDaemonOptimizer(config)._write_progress_summary(cycle_results=[latest], completed_cycles=1)

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["failure_kind_counts"]["typescript_quality"] == 1
    assert progress["latest_round"]["failure_kind"] == "typescript_quality"
    assert progress["current_task_failure_counts"]["by_kind_since_success"]["typescript_quality"] == 1
    assert progress["typescript_quality_failures"]["consecutive"] == 1
    assert progress["typescript_quality_failures"]["top_signature_count"] == 1
    assert "TS2314:Generic type '<symbol>' requires 2 type argument(s)." in progress["typescript_quality_failures"]["top_signature"]
    assert progress["rollback_quality_failures"]["total"] == 1
    assert progress["rollback_quality_failures"]["consecutive"] == 1
    assert progress["rollback_quality_failures"]["by_kind"]["typescript_quality"] == 1

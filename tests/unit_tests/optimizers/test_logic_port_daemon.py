import json
import subprocess
from pathlib import Path

import ipfs_datasets_py.optimizers.logic_port_daemon as logic_port_daemon
from ipfs_datasets_py.optimizers.logic_port_daemon import (
    DEFAULT_PLAN_DOCS,
    LogicPortDaemonConfig,
    LogicPortDaemonOptimizer,
    extract_plan_tasks,
    parse_llm_patch_response,
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


def test_default_plan_docs_use_typescript_port_plan():
    assert DEFAULT_PLAN_DOCS == ("docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md",)


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
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
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
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
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
        typescript_logic_dir=logic_dir,
        python_logic_dir=python_logic_dir,
        task_board_doc=plan,
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
    assert router.calls[0]["kwargs"]["provider"] == "codex_cli"
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
    assert any(path.suffix == ".patch" for path in artifact_files)
    assert any(path.name.endswith(".stat.txt") for path in artifact_files)


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
            return ["Rejected proposal because TypeScript replacement preflight found parser or generic/type-quality errors before touching the worktree."]
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

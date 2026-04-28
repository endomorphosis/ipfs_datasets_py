import json
from pathlib import Path

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
    assert router.calls[0]["kwargs"]["timeout"] == 900
    assert router.calls[0]["kwargs"]["trace"] is True
    assert router.calls[0]["kwargs"]["trace_dir"].endswith("ipfs_datasets_py/.daemon/codex-runs")
    assert "DETERMINISTIC" not in router.calls[0]["prompt"] or "Port deterministic parser IR" in router.calls[0]["prompt"]
    assert result["valid"] is True
    assert result["artifact"]["has_patch"] is True
    assert not (tmp_path / "new-file.txt").exists()


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
    plan.write_text("- [ ] Add usable parity fixture\n- [ ] Implement next feature\n", encoding="utf-8")
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
    assert "- [x] Add usable parity fixture" in updated
    assert "Current target: `Task checkbox-2: Implement next feature`" in updated
    assert "- Accepted changed files: `docs/fixture.md`" in updated
    assert result["artifact"]["changed_files"] == ["docs/fixture.md"]


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

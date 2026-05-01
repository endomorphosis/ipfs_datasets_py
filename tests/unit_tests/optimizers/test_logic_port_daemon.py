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
    assert "Do not return another patch" in router.calls[-1]["prompt"]


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

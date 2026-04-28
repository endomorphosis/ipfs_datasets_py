import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_port_daemon import (
    LogicPortDaemonConfig,
    LogicPortDaemonOptimizer,
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


def test_parse_llm_patch_response_from_fenced_diff():
    artifact = parse_llm_patch_response(
        "Here is the patch:\n```diff\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n```\n"
    )

    assert "diff --git" in artifact.patch
    assert artifact.errors == []


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

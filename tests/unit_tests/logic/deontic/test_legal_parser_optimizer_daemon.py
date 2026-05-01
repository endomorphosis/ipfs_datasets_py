"""Tests for the deterministic legal parser optimizer daemon."""

import json
import time

from ipfs_datasets_py.optimizers.logic.deontic.parser_daemon import (
    LegalParserDaemonConfig,
    LegalParserCycleProposal,
    LegalParserOptimizerDaemon,
    LegalParserParityOptimizer,
    parse_cycle_proposal,
)


class _FakeRouter:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def generate(self, prompt, method, max_tokens=2000, temperature=0.7, router_kwargs=None):
        self.calls.append(
            {
                "prompt": prompt,
                "method": method,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "router_kwargs": router_kwargs or {},
            }
        )
        return self.response


class _SequencedRouter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, prompt, method, max_tokens=2000, temperature=0.7, router_kwargs=None):
        self.calls.append(
            {
                "prompt": prompt,
                "method": method,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "router_kwargs": router_kwargs or {},
            }
        )
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


class _FailingOptimizer:
    def generate(self, input_data, context):
        raise RuntimeError("boom before proposal")


class _MetricGateOptimizer(LegalParserParityOptimizer):
    def __init__(self, *, daemon_config, llm_backend, initial_evaluation, post_evaluation):
        super().__init__(daemon_config=daemon_config, llm_backend=llm_backend)
        self.initial_evaluation = initial_evaluation
        self.post_evaluation = post_evaluation

    def generate(self, input_data, context):
        return self.initial_evaluation

    def evaluate_current_parser(self):
        return self.post_evaluation

    def run_tests(self):
        return {"valid": True, "returncode": 0, "stdout": "passed", "stderr": ""}


def test_parse_cycle_proposal_accepts_strict_json():
    raw = json.dumps(
        {
            "summary": "Add deterministic coverage.",
            "focus_area": "parser",
            "requirements_addressed": ["Phase 4"],
            "acceptance_criteria": ["parser behavior is covered"],
            "changed_files": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "expected_metric_gain": {"parsed_rate": 0.1},
            "tests_to_run": ["pytest tests/unit_tests/logic/deontic"],
            "unified_diff": "diff --git a/x b/x\n",
        }
    )

    proposal = parse_cycle_proposal(raw)

    assert proposal.summary == "Add deterministic coverage."
    assert proposal.focus_area == "parser"
    assert proposal.requirements_addressed == ["Phase 4"]
    assert proposal.acceptance_criteria == ["parser behavior is covered"]
    assert proposal.changed_files == ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"]
    assert proposal.expected_metric_gain == {"parsed_rate": 0.1}
    assert proposal.unified_diff.startswith("diff --git")
    assert proposal.parse_error == ""


def test_optimizer_builds_gpt55_router_request_without_calling_real_llm(tmp_path):
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "No-op patch for test.",
                "requirements_addressed": [],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": "",
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        model_name="gpt-5.5",
        provider="openai",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)

    proposal = optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])

    assert proposal.summary == "No-op patch for test."
    assert fake_router.calls
    call = fake_router.calls[0]
    assert call["router_kwargs"]["provider"] == "openai"
    assert call["router_kwargs"]["model_name"] == "gpt-5.5"
    assert call["router_kwargs"]["allow_local_fallback"] is False
    assert call["router_kwargs"]["disable_model_retry"] is True


def test_daemon_cycle_writes_artifacts_in_patch_only_mode(tmp_path):
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "No-op patch for test.",
                "requirements_addressed": ["daemon"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": "",
            }
        )
    )
    repo_root = tmp_path
    (repo_root / "docs/logic").mkdir(parents=True)
    (repo_root / "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md").write_text("Improve parser.", encoding="utf-8")
    (repo_root / "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md").write_text("Implement parser.", encoding="utf-8")
    config = LegalParserDaemonConfig(
        repo_root=repo_root,
        output_dir=repo_root / "out",
        run_tests=False,
        apply_patches=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert cycle["cycle_index"] == 1
    assert cycle["apply_result"] == {"applied": False, "reason": "apply_patches_disabled"}
    assert cycle["metrics"]["probe_sample_count"] > 0
    assert (repo_root / "out/cycles/cycle_0001/proposal.json").exists()
    assert (repo_root / "out/cycles/cycle_0001/cycle_started.json").exists()
    assert (repo_root / "out/latest_summary.json").exists()
    assert (repo_root / "out/progress_summary.json").exists()
    status = json.loads((repo_root / "out/current_status.json").read_text(encoding="utf-8"))
    assert status["phase"] == "cycle_completed"
    assert status["cycle_index"] == 1
    assert status["apply_result"]["reason"] == "apply_patches_disabled"


def test_evaluation_uses_active_repair_projection_for_probe_metrics(tmp_path):
    """Daemon repair details should not use stale raw llm_repair flags."""

    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    evaluation = optimizer.evaluate_current_parser()

    assert evaluation["metrics"]["repair_required_count"] == 1
    assert evaluation["repair_required"] == [evaluation["repair_required_details"][0]["source_id"]]
    assert [detail["sample_id"] for detail in evaluation["repair_required_details"]] == [
        "cross_reference"
    ]
    assert evaluation["metrics"]["coverage_gaps"] == ["repair_required_count: 1"]


def test_daemon_reports_invalid_patch_as_patch_check_failed(tmp_path):
    __import__("subprocess").run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Malformed patch for test.",
                "requirements_addressed": ["daemon"],
                "acceptance_criteria": ["invalid diff is reported precisely"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": "not a diff",
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=True,
        run_tests=False,
        require_production_and_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert cycle["patch_check"]["valid"] is False
    assert cycle["proposal_quality"]["valid"] is True
    assert cycle["apply_result"]["reason"] == "patch_check_failed"
    assert cycle["tests"]["reason"] == "patch_not_applied"
    status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    assert status["phase"] == "cycle_completed"
    assert status["apply_result"]["reason"] == "patch_check_failed"


def test_daemon_retries_empty_or_unparseable_llm_proposals(tmp_path):
    (tmp_path / "x.txt").write_text("before\n", encoding="utf-8")
    valid_diff = "\n".join(
        [
            "diff --git a/x.txt b/x.txt",
            "--- a/x.txt",
            "+++ b/x.txt",
            "@@ -1 +1 @@",
            "-before",
            "+after",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            '{"type":"thread.started"}\n{"type":"turn.started"}',
            json.dumps(
                {
                    "summary": "Retry produced a patch.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["retry result is recorded"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": valid_diff,
                }
            ),
        ]
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=False,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert cycle["proposal_attempts"][0]["retry_reason"].startswith("parse_error:")
    assert cycle["proposal_attempts"][1]["retry_reason"] == ""
    assert cycle["proposal_attempts"][1]["summary"] == "Retry produced a patch."


def test_daemon_retries_patch_check_failures_with_feedback(tmp_path):
    (tmp_path / "x.txt").write_text("before\n", encoding="utf-8")
    valid_diff = "\n".join(
        [
            "diff --git a/x.txt b/x.txt",
            "--- a/x.txt",
            "+++ b/x.txt",
            "@@ -1 +1 @@",
            "-before",
            "+after",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "First patch has stale context.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["patch check retries"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": "not a diff",
                }
            ),
            json.dumps(
                {
                    "summary": "Second patch applies.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["patch applies"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": valid_diff,
                }
            ),
        ]
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=False,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert "patch_check_failed" in cycle["proposal_attempts"][0]["retry_reason"]
    assert cycle["proposal_attempts"][1]["patch_valid"] is True
    assert cycle["patch_check"]["valid"] is True
    assert cycle["apply_result"]["reason"] == "apply_patches_disabled"
    assert "previous proposal attempt 1 was rejected" in fake_router.calls[1]["prompt"]


def test_daemon_heartbeat_refreshes_current_status_while_blocked(tmp_path):
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        heartbeat_interval_seconds=0.01,
    )
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-04-28T00:00:00+00:00",
    )

    daemon._start_heartbeat()
    try:
        status = {}
        deadline = time.time() + 1.0
        while time.time() < deadline:
            status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
            if "heartbeat_pid" in status:
                break
            time.sleep(0.02)
    finally:
        daemon._stop_heartbeat()

    assert status["phase"] == "requesting_llm_patch"
    assert status["heartbeat_pid"] > 0
    assert status["heartbeat_thread"] == "legal-parser-daemon-heartbeat"


def test_daemon_records_cycle_exception_instead_of_exiting(tmp_path):
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        max_cycles=1,
        run_tests=False,
        error_backoff_seconds=0,
    )
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    summary = __import__("asyncio").run(daemon.run())

    cycle = summary["latest_cycle"]
    assert cycle["status"] == "cycle_error"
    assert cycle["cycle_index"] == 1
    assert cycle["exception"]["type"] == "RuntimeError"
    assert "boom before proposal" in cycle["exception"]["message"]
    assert (tmp_path / "out/cycles/cycle_0001/cycle_summary.json").exists()
    assert (tmp_path / "out/latest_summary.json").exists()
    status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    assert status["phase"] == "cycle_error_recorded"
    assert status["exception"]["type"] == "RuntimeError"


def test_daemon_rejects_valid_patch_without_production_and_test_files(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(
        summary="Docs only.",
        acceptance_criteria=["docs changed"],
        changed_files=["docs/logic/example.md"],
    )

    quality = daemon._assess_proposal_quality(proposal, ["docs/logic/example.md"])

    assert quality["valid"] is False
    assert "patch must touch at least one production deontic parser/export file" in quality["reasons"]
    assert "patch must touch at least one deontic parser test file" in quality["reasons"]


def test_daemon_rolls_back_patch_that_breaks_python_compile(tmp_path):
    production = tmp_path / "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    test_file = tmp_path / "tests/unit_tests/logic/deontic/test_deontic_parser.py"
    production.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    unified_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py b/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "--- a/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "+++ b/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "@@ -1 +1 @@",
            "-VALUE = 1",
            "+def broken(:",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_parser.py b/tests/unit_tests/logic/deontic/test_deontic_parser.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_parser.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_parser.py",
            "@@ -1,2 +1,3 @@",
            " def test_placeholder():",
            "     assert True",
            "+",
            "",
        ]
    )
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Introduce invalid syntax.",
                "requirements_addressed": ["daemon validation"],
                "acceptance_criteria": ["invalid Python is rolled back"],
                "expected_metric_gain": {"parsed_rate": 0.1},
                "tests_to_run": [],
                "unified_diff": unified_diff,
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=True,
        run_tests=False,
        require_clean_touched_files=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert cycle["apply_result"]["applied"] is True
    assert cycle["apply_result"]["rolled_back"] is True
    assert cycle["apply_result"]["reason"] == "post_apply_validation_failed"
    assert cycle["post_apply_validation"]["valid"] is False
    assert "changed Python files failed py_compile" in cycle["post_apply_validation"]["reasons"]
    assert production.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_daemon_writes_accepted_change_ledger_and_progress_summary(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    proposal_path = cycle_dir / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "summary": "Improve parser behavior.",
                "focus_area": "parser",
                "requirements_addressed": ["roadmap"],
                "acceptance_criteria": ["tests pass"],
            }
        ),
        encoding="utf-8",
    )
    cycle = {
        "cycle_index": 1,
        "finished_at": "2026-04-28T00:00:00+00:00",
        "proposal_path": str(proposal_path),
        "changed_files": [
            "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "tests/unit_tests/logic/deontic/test_deontic_converter.py",
        ],
        "production_files": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
        "test_files": ["tests/unit_tests/logic/deontic/test_deontic_converter.py"],
        "patch_stats": {"files_changed": 2, "insertions": 3, "deletions": 1},
        "retained_change": {
            "has_retained_changes": True,
            "changed_files": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
        },
        "commit_result": {"committed": False, "reason": "disabled"},
        "score": 0.5,
        "metrics": {"parity_score": 0.5, "coverage_gaps": ["gap"]},
        "post_evaluation": {"metrics": {"parity_score": 0.6}},
        "apply_result": {"applied": True},
        "tests": {"valid": True},
        "patch_check": {"valid": True},
    }

    daemon._record_progress(cycle)

    ledger = tmp_path / "out/accepted_changes.jsonl"
    progress = tmp_path / "out/progress_summary.json"
    assert ledger.exists()
    assert "Improve parser behavior." in ledger.read_text(encoding="utf-8")
    progress_payload = json.loads(progress.read_text(encoding="utf-8"))
    assert progress_payload["accepted_patch_count"] == 1
    assert progress_payload["retained_accepted_patch_count"] == 1
    assert progress_payload["latest_cycle"]["changed_files"] == cycle["changed_files"]
    assert progress_payload["latest_cycle"]["retained_change"]["has_retained_changes"] is True
    assert progress_payload["latest_cycle"]["commit_result"]["committed"] is False


def test_recent_cycle_history_includes_patch_failure_feedback(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    proposal_path = cycle_dir / "proposal.json"
    proposal_path.write_text(
        json.dumps({"summary": "Patch stale context.", "requirements_addressed": ["roadmap"]}),
        encoding="utf-8",
    )
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "score": 0.9,
                "feedback": ["gap"],
                "proposal_path": str(proposal_path),
                "patch_check": {"valid": False, "stderr": "error: patch failed: file.py:10"},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {"applied": False, "reason": "patch_check_failed"},
                "changed_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
                "tests": {"valid": True},
            }
        ),
        encoding="utf-8",
    )

    history = optimizer._recent_cycle_history(limit=1)

    assert history[0]["patch_valid"] is False
    assert "patch failed" in history[0]["patch_failure_tail"]
    assert history[0]["apply_reason"] == "patch_check_failed"
    assert history[0]["changed_files"] == ["ipfs_datasets_py/logic/deontic/formula_builder.py"]


def test_recent_cycle_history_summarizes_test_failures_for_recovery_prompt(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "score": 0.9,
                "feedback": ["repair_required_count: 1"],
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {"applied": True, "rolled_back": True},
                "changed_files": ["ipfs_datasets_py/logic/deontic/exports.py"],
                "tests": {
                    "valid": False,
                    "stdout": "\n".join(
                        [
                            "E   RecursionError: maximum recursion depth exceeded",
                            "!!! Recursion detected (same locals & position)",
                            "FAILED tests/unit_tests/logic/deontic/test_deontic_exports.py::test_export_tables - RecursionError",
                        ]
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    history = optimizer._recent_cycle_history(limit=1)
    recent_failures = optimizer._recent_test_failures(history)
    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert history[0]["tests_valid"] is False
    assert history[0]["test_failure_summary"]["exception_types"] == ["RecursionError"]
    assert recent_failures[0]["failed_tests"] == [
        "tests/unit_tests/logic/deontic/test_deontic_exports.py::test_export_tables"
    ]
    assert recent_failures[0]["rolled_back"] is True
    assert '"test_failure_recovery_mode": true' in prompt
    assert "RecursionError" in prompt
    assert "recent_test_failures" in prompt


def test_test_failure_files_receive_expanded_snapshots_in_prompt(tmp_path):
    target_file = "ipfs_datasets_py/logic/deontic/exports.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_exports.py"
    for path, body in {
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md": "Improve parser.",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md": "Implement parser.",
        target_file: "A" * 25000 + "\nMIDDLE_FAILURE_HELPER\n" + "B" * 25000,
        test_file: "def test_existing():\n    assert True\n",
    }.items():
        full_path = tmp_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {"applied": True, "rolled_back": True},
                "changed_files": [target_file, test_file],
                "tests": {
                    "valid": False,
                    "stdout": "FAILED tests/unit_tests/logic/deontic/test_deontic_exports.py::test_export_tables - RecursionError",
                },
            }
        ),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        target_files=(target_file, test_file),
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    history = optimizer._recent_cycle_history(limit=1)
    recent_failures = optimizer._recent_test_failures(history)
    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert optimizer._recent_test_failed_files(recent_failures) == [target_file, test_file]
    assert '"recent_test_failed_files": [' in prompt
    assert "MIDDLE_FAILURE_HELPER" in prompt


def test_metric_stall_no_progress_failures_are_prompt_feedback(tmp_path):
    target_file = "ipfs_datasets_py/logic/deontic/exports.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_exports.py"
    for path, body in {
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md": "Improve parser.",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md": "Implement parser.",
        target_file: "A" * 25000 + "\nMETRIC_STALL_HELPER\n" + "B" * 25000,
        test_file: "def test_existing():\n    assert True\n",
    }.items():
        full_path = tmp_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "proposal_path": str(cycle_dir / "proposal.json"),
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {
                    "applied": True,
                    "rolled_back": True,
                    "reason": "metric_stall_no_metric_progress",
                    "metric_progress": {
                        "valid": False,
                        "expected_metric_gain": {"repair_required_count": -1},
                        "pre_metrics": {"repair_required_count": 1, "parity_score": 0.9763},
                        "post_metrics": {"repair_required_count": 1, "parity_score": 0.9763},
                        "moved_expected_metrics": {},
                        "score_delta": 0.0,
                        "feedback_reduced": False,
                        "reasons": ["metric-stall patch passed tests but did not improve claimed metrics"],
                    },
                },
                "changed_files": [target_file, test_file],
                "tests": {"valid": True, "stdout": "passed"},
            }
        ),
        encoding="utf-8",
    )
    (cycle_dir / "proposal.json").write_text(
        json.dumps({"summary": "Exports-only context recovery did not move metrics."}),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        target_files=(target_file, test_file),
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    history = optimizer._recent_cycle_history(limit=1)
    failures = optimizer._recent_metric_stall_failures(history)
    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert failures[0]["expected_metric_gain"] == {"repair_required_count": -1}
    assert failures[0]["pre_metrics"]["repair_required_count"] == 1
    assert optimizer._recent_metric_stall_failed_files(failures) == [target_file, test_file]
    assert '"metric_no_progress_recovery_mode": true' in prompt
    assert "recent_metric_stall_failures" in prompt
    assert "METRIC_STALL_HELPER" in prompt


def test_optimizer_enters_patch_stability_mode_after_repeated_patch_check_failures(tmp_path):
    target_file = "ipfs_datasets_py/logic/deontic/formula_builder.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py"
    for path, body in {
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md": "Improve parser.",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md": "Implement parser.",
        target_file: "def existing():\n    return 'production'\n",
        test_file: "def test_existing():\n    assert True\n",
    }.items():
        full_path = tmp_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    cycles_dir = tmp_path / "out/cycles"
    for index in range(1, 4):
        cycle_dir = cycles_dir / f"cycle_{index:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(
            json.dumps(
                {
                    "cycle_index": index,
                    "score": 0.9,
                    "feedback": ["gap"],
                    "patch_check": {"valid": False, "stderr": "error: patch failed"},
                    "proposal_quality": {"valid": True, "reasons": []},
                    "apply_result": {"applied": False, "reason": "patch_check_failed"},
                    "changed_files": [target_file, test_file],
                    "tests": {"valid": True},
                }
            ),
            encoding="utf-8",
        )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        docs=(
            "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md",
            "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md",
        ),
        target_files=(target_file, test_file),
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    history = optimizer._recent_cycle_history(limit=5)
    prompt = optimizer.build_patch_prompt(cycle_index=4, evaluation={"metrics": {}}, feedback=["gap"])

    assert optimizer._patch_stability_mode(history) is True
    assert optimizer._recent_failed_patch_files(history) == [target_file, test_file]
    assert '"patch_stability_mode": true' in prompt
    assert '"recent_failed_patch_files": [' in prompt
    assert "prefer one production file plus one matching test file" in prompt


def test_daemon_retries_broad_patch_when_patch_stability_mode_is_active(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    files = {
        "ipfs_datasets_py/logic/deontic/formula_builder.py": "before_formula\n",
        "ipfs_datasets_py/logic/deontic/exports.py": "before_exports\n",
        "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py": "before_test\n",
    }
    for path, body in files.items():
        full_path = repo / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    cycles_dir = repo / "out/cycles"
    for index in range(101, 104):
        cycle_dir = cycles_dir / f"cycle_{index:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(
            json.dumps(
                {
                    "cycle_index": index,
                    "patch_check": {"valid": False, "stderr": "error: patch failed"},
                    "proposal_quality": {"valid": True, "reasons": []},
                    "apply_result": {"applied": False, "reason": "patch_check_failed"},
                    "changed_files": list(files),
                    "tests": {"valid": True},
                }
            ),
            encoding="utf-8",
        )
    broad_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/formula_builder.py b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "--- a/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "+++ b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "@@ -1 +1 @@",
            "-before_formula",
            "+after_formula",
            "diff --git a/ipfs_datasets_py/logic/deontic/exports.py b/ipfs_datasets_py/logic/deontic/exports.py",
            "--- a/ipfs_datasets_py/logic/deontic/exports.py",
            "+++ b/ipfs_datasets_py/logic/deontic/exports.py",
            "@@ -1 +1 @@",
            "-before_exports",
            "+after_exports",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "@@ -1 +1 @@",
            "-before_test",
            "+after_test",
            "",
        ]
    )
    focused_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/formula_builder.py b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "--- a/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "+++ b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "@@ -1 +1 @@",
            "-before_formula",
            "+after_formula",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "@@ -1 +1 @@",
            "-before_test",
            "+after_test",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "Broad patch should be retried.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["stability mode rejects broad patches"],
                    "expected_metric_gain": {"repair_required_count": -1},
                    "tests_to_run": [],
                    "unified_diff": broad_diff,
                }
            ),
            json.dumps(
                {
                    "summary": "Focused patch should pass quality.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["stability mode accepts focused patches"],
                    "expected_metric_gain": {"repair_required_count": -1},
                    "tests_to_run": [],
                    "unified_diff": focused_diff,
                }
            ),
        ]
    )
    config = LegalParserDaemonConfig(
        repo_root=repo,
        output_dir=repo / "out",
        apply_patches=False,
        run_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert "patch stability mode allows at most two changed files" in cycle["proposal_attempts"][0]["retry_reason"]
    assert cycle["proposal_attempts"][1]["proposal_quality_valid"] is True
    assert cycle["proposal_quality"]["valid"] is True
    assert cycle["apply_result"]["reason"] == "apply_patches_disabled"


def test_optimizer_prompt_marks_metric_stall_and_includes_repair_details(tmp_path):
    target_file = "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_converter.py"
    for path, body in {
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md": "Improve parser.",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md": "Implement parser.",
        target_file: "def existing():\n    return 'production'\n",
        test_file: "def test_existing():\n    assert True\n",
    }.items():
        full_path = tmp_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "progress_summary.json").write_text(
        json.dumps(
            {
                "stalled_metric_cycles": 5,
                "current_score": 0.9763,
                "current_feedback": ["repair_required_count: 4"],
            }
        ),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=out_dir,
        target_files=(target_file, test_file),
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    prompt = optimizer.build_patch_prompt(
        cycle_index=10,
        evaluation={
            "metrics": {"parity_score": 0.9763, "coverage_gaps": ["repair_required_count: 4"]},
            "repair_required_details": [
                {
                    "sample_id": "cross_reference",
                    "text": "The Secretary shall publish the notice except as provided in section 552.",
                    "parser_warnings": ["cross_reference_requires_resolution"],
                }
            ],
        },
        feedback=["repair_required_count: 4"],
    )

    assert '"metric_stall_mode": true' in prompt
    assert "cross_reference" in prompt
    assert "expected_metric_gain for a real metric" in prompt


def test_evaluation_records_repair_required_details():
    optimizer = LegalParserParityOptimizer(daemon_config=LegalParserDaemonConfig())

    evaluation = optimizer.evaluate_current_parser()

    assert evaluation["repair_required_details"]
    detail = evaluation["repair_required_details"][0]
    assert {"sample_id", "text", "source_id", "parser_warnings", "llm_repair"} <= set(detail)


def test_daemon_retries_metric_stall_proposal_without_expected_metric_gain(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    files = {
        "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py": "before_parser\n",
        "tests/unit_tests/logic/deontic/test_deontic_converter.py": "before_test\n",
    }
    for path, body in files.items():
        full_path = repo / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    out_dir = repo / "out"
    out_dir.mkdir()
    (out_dir / "progress_summary.json").write_text(
        json.dumps({"stalled_metric_cycles": 4, "current_score": 0.9763}),
        encoding="utf-8",
    )
    diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py b/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "--- a/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "+++ b/ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
            "@@ -1 +1 @@",
            "-before_parser",
            "+after_parser",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_converter.py b/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "@@ -1 +1 @@",
            "-before_test",
            "+after_test",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "Patch omits metric gain.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["metric stall proposal is rejected"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": diff,
                }
            ),
            json.dumps(
                {
                    "summary": "Patch names metric gain.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["repair-required count moves"],
                    "expected_metric_gain": {"repair_required_count": -1},
                    "tests_to_run": [],
                    "unified_diff": diff,
                }
            ),
        ]
    )
    config = LegalParserDaemonConfig(
        repo_root=repo,
        output_dir=out_dir,
        apply_patches=False,
        run_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert "metric stall mode requires expected_metric_gain" in cycle["proposal_attempts"][0]["retry_reason"]
    assert cycle["proposal_attempts"][1]["proposal_quality_valid"] is True
    assert cycle["proposal_quality"]["valid"] is True
    assert cycle["apply_result"]["reason"] == "apply_patches_disabled"


def test_daemon_rolls_back_metric_stall_patch_without_metric_progress(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    prod_file = "ipfs_datasets_py/logic/deontic/exports.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_exports.py"
    for path, body in {
        prod_file: "EXPORT_MARKER = 'before_exports'\n",
        test_file: "def test_marker():\n    assert 'before_test'\n",
    }.items():
        full_path = repo / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    out_dir = repo / "out"
    out_dir.mkdir()
    (out_dir / "progress_summary.json").write_text(
        json.dumps({"stalled_metric_cycles": 5, "current_score": 0.9763}),
        encoding="utf-8",
    )
    diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/exports.py b/ipfs_datasets_py/logic/deontic/exports.py",
            "--- a/ipfs_datasets_py/logic/deontic/exports.py",
            "+++ b/ipfs_datasets_py/logic/deontic/exports.py",
            "@@ -1 +1 @@",
            "-EXPORT_MARKER = 'before_exports'",
            "+EXPORT_MARKER = 'after_exports'",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_exports.py b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "@@ -1,2 +1,2 @@",
            " def test_marker():",
            "-    assert 'before_test'",
            "+    assert 'after_test'",
            "",
        ]
    )
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Patch claims repair progress but leaves metrics flat.",
                "requirements_addressed": ["daemon"],
                "acceptance_criteria": ["repair-required count moves"],
                "expected_metric_gain": {"repair_required_count": -1},
                "tests_to_run": [],
                "unified_diff": diff,
            }
        )
    )
    initial_evaluation = {
        "metrics": {
            "parity_score": 0.9763,
            "repair_required_count": 1,
            "coverage_gaps": ["repair_required_count: 1"],
        }
    }
    post_evaluation = {
        "metrics": {
            "parity_score": 0.9763,
            "repair_required_count": 1,
            "coverage_gaps": ["repair_required_count: 1"],
        }
    }
    config = LegalParserDaemonConfig(
        repo_root=repo,
        output_dir=out_dir,
        apply_patches=True,
        run_tests=True,
        commit_accepted_patches=True,
        require_clean_touched_files=False,
        llm_proposal_attempts=1,
    )
    optimizer = _MetricGateOptimizer(
        daemon_config=config,
        llm_backend=fake_router,
        initial_evaluation=initial_evaluation,
        post_evaluation=post_evaluation,
    )
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert cycle["tests"]["valid"] is True
    assert cycle["apply_result"]["rolled_back"] is True
    assert cycle["apply_result"]["reason"] == "metric_stall_no_metric_progress"
    assert cycle["retained_change"]["has_retained_changes"] is False
    assert cycle["retained_change"]["reason"] == "metric_stall_no_metric_progress"
    assert cycle["commit_result"] == {"committed": False, "reason": "metric_stall_no_metric_progress"}
    assert (repo / prod_file).read_text(encoding="utf-8") == "EXPORT_MARKER = 'before_exports'\n"
    assert (repo / test_file).read_text(encoding="utf-8") == "def test_marker():\n    assert 'before_test'\n"


def test_daemon_retries_exports_only_patch_after_metric_no_progress_recovery(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    files = {
        "ipfs_datasets_py/logic/deontic/exports.py": "before_exports\n",
        "ipfs_datasets_py/logic/deontic/formula_builder.py": "before_formula\n",
        "tests/unit_tests/logic/deontic/test_deontic_exports.py": "before_exports_test\n",
        "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py": "before_formula_test\n",
    }
    for path, body in files.items():
        full_path = repo / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body, encoding="utf-8")
    cycle_dir = repo / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {
                    "applied": True,
                    "rolled_back": True,
                    "reason": "metric_stall_no_metric_progress",
                    "metric_progress": {
                        "valid": False,
                        "expected_metric_gain": {"repair_required_count": -1},
                        "pre_metrics": {"repair_required_count": 1},
                        "post_metrics": {"repair_required_count": 1},
                        "moved_expected_metrics": {},
                    },
                },
                "changed_files": [
                    "ipfs_datasets_py/logic/deontic/exports.py",
                    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
                ],
                "tests": {"valid": True, "stdout": "passed"},
            }
        ),
        encoding="utf-8",
    )
    exports_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/exports.py b/ipfs_datasets_py/logic/deontic/exports.py",
            "--- a/ipfs_datasets_py/logic/deontic/exports.py",
            "+++ b/ipfs_datasets_py/logic/deontic/exports.py",
            "@@ -1 +1 @@",
            "-before_exports",
            "+after_exports",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_exports.py b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "@@ -1 +1 @@",
            "-before_exports_test",
            "+after_exports_test",
            "",
        ]
    )
    formula_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/formula_builder.py b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "--- a/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "+++ b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "@@ -1 +1 @@",
            "-before_formula",
            "+after_formula",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "@@ -1 +1 @@",
            "-before_formula_test",
            "+after_formula_test",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "Exports-only patch should be retried.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["metric moves"],
                    "expected_metric_gain": {"repair_required_count": -1},
                    "tests_to_run": [],
                    "unified_diff": exports_diff,
                }
            ),
            json.dumps(
                {
                    "summary": "Formula patch can proceed.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["metric moves"],
                    "expected_metric_gain": {"repair_required_count": -1},
                    "tests_to_run": [],
                    "unified_diff": formula_diff,
                }
            ),
        ]
    )
    config = LegalParserDaemonConfig(
        repo_root=repo,
        output_dir=repo / "out",
        apply_patches=False,
        run_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=2)

    assert len(fake_router.calls) == 2
    assert "metric no-progress recovery requires a non-exports production" in cycle["proposal_attempts"][0]["retry_reason"]
    assert cycle["proposal_attempts"][1]["proposal_quality_valid"] is True
    assert cycle["proposal_quality"]["valid"] is True
    assert cycle["changed_files"] == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py",
        "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    ]


def test_metric_no_progress_recovery_rejects_clearing_unresolved_reference_repair(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(
        summary=(
            "Reclassify unresolved numbered reference-only exceptions as validation blockers "
            "rather than active LLM repair to reduce repair_required_count."
        ),
        acceptance_criteria=["unresolved numbered reference stops counting as active repair"],
        expected_metric_gain={"repair_required_count": -1},
    )
    quality = {
        "valid": True,
        "reasons": [],
        "production_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
        "test_files": ["tests/unit_tests/logic/deontic/test_deontic_formula_builder.py"],
    }

    result = daemon._enforce_metric_no_progress_recovery_quality(
        proposal=proposal,
        proposal_quality=quality,
        changed_files=[
            "ipfs_datasets_py/logic/deontic/formula_builder.py",
            "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
        ],
    )

    assert result["valid"] is False
    assert any("cannot clear active repair" in reason for reason in result["reasons"])


def test_metric_no_progress_recovery_allows_exact_same_document_reference_fix(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(
        summary="Resolve numbered references only when exact same-document evidence proves the target section exists.",
        acceptance_criteria=["absent and mismatched references remain blocked"],
        expected_metric_gain={"cross_reference_resolution_rate": 0.1},
    )
    quality = {
        "valid": True,
        "reasons": [],
        "production_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
        "test_files": ["tests/unit_tests/logic/deontic/test_deontic_formula_builder.py"],
    }

    result = daemon._enforce_metric_no_progress_recovery_quality(
        proposal=proposal,
        proposal_quality=quality,
        changed_files=[
            "ipfs_datasets_py/logic/deontic/formula_builder.py",
            "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
        ],
    )

    assert result["valid"] is True
    assert result["reasons"] == []


def test_metric_stall_retention_accepts_claimed_metric_progress(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(expected_metric_gain={"repair_required_count": -1})

    result = daemon._metric_stall_retention_result(
        proposal=proposal,
        evaluation={"metrics": {"parity_score": 0.9, "repair_required_count": 2}},
        post_evaluation={"metrics": {"parity_score": 0.9, "repair_required_count": 1}},
        metric_stall_mode=True,
    )

    assert result["valid"] is True
    assert result["moved_expected_metrics"]["repair_required_count"]["before"] == 2.0
    assert result["moved_expected_metrics"]["repair_required_count"]["after"] == 1.0


def test_retained_change_summary_detects_no_content_change(tmp_path):
    path = tmp_path / "ipfs_datasets_py/logic/deontic/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("same", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    retained = daemon._retained_change_summary({"ipfs_datasets_py/logic/deontic/example.py": "same"})

    assert retained["has_retained_changes"] is False
    assert retained["reason"] == "no_file_content_changed_after_apply"


def test_retained_change_summary_detects_changed_file(tmp_path):
    path = tmp_path / "ipfs_datasets_py/logic/deontic/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("after", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    retained = daemon._retained_change_summary({"ipfs_datasets_py/logic/deontic/example.py": "before"})

    assert retained["has_retained_changes"] is True
    assert retained["changed_files"] == ["ipfs_datasets_py/logic/deontic/example.py"]


def test_dirty_touched_files_reports_uncommitted_target_file(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    path = repo / "ipfs_datasets_py/logic/deontic/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("before\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    path.write_text("after\n", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    dirty = daemon._dirty_touched_files(["ipfs_datasets_py/logic/deontic/example.py"])

    assert dirty == ["ipfs_datasets_py/logic/deontic/example.py"]


def test_progress_report_names_visible_commits_and_uncommitted_files(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    progress = {
        "updated_at": "2026-04-28T00:00:00+00:00",
        "run": {"run_id": "run-1", "baseline_head": "abc123"},
        "total_cycles": 3,
        "retained_accepted_patch_count": 1,
        "rolled_back_count": 1,
        "rejected_patch_count": 1,
        "current_score": 0.9,
        "score_delta": 0.1,
        "current_feedback": ["repair_required_count: 1"],
        "git_retained_work": {
            "head": "def456",
            "commits_since_run_start": ["def456 legal-parser-daemon: cycle 2 retained parser improvement"],
            "uncommitted_files": ["M ipfs_datasets_py/logic/deontic/formula_builder.py"],
            "diff_since_run_start_stat": "formula_builder.py | 3 ++-",
        },
        "accepted_change_summaries": [
            {
                "cycle_index": 2,
                "summary": "Improve formula export.",
                "changed_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
            }
        ],
        "recent_rejections": [
            {
                "cycle_index": 4,
                "reason": "patch_check_failed:error: patch failed",
                "changed_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
            }
        ],
    }

    report = daemon._format_progress_report(progress)

    assert "def456 legal-parser-daemon" in report
    assert "M ipfs_datasets_py/logic/deontic/formula_builder.py" in report
    assert "Improve formula export." in report
    assert "repair_required_count: 1" in report
    assert "patch_check_failed:error: patch failed" in report

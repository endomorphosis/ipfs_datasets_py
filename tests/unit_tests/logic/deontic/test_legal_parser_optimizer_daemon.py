"""Tests for the deterministic legal parser optimizer daemon."""

import json
import time
from pathlib import Path

import ipfs_datasets_py.optimizers.logic.deontic.parser_daemon as parser_daemon_module
from ipfs_datasets_py.optimizers.logic.deontic.parser_daemon import (
    LegalParserDaemonConfig,
    LegalParserCycleProposal,
    LegalParserOptimizerDaemon,
    LegalParserParityOptimizer,
    _paths_from_git_status_porcelain,
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


def test_supervisor_revalidates_agentic_reason_after_stopping_child():
    repo_root = Path(__file__).resolve().parents[4]
    script = (
        repo_root / "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh"
    ).read_text(encoding="utf-8")
    function_start = script.index("run_agentic_maintenance() {")
    function_end = script.index("\nheartbeat_is_stale() {", function_start)
    function_body = script[function_start:function_end]

    assert function_body.index("stop_child") < function_body.index(
        'refreshed_reason="$(agentic_maintenance_reason || true)"'
    )
    assert "skipped_stale_trigger" in function_body
    assert "trigger cleared after child stop" in function_body
    assert function_body.index('if [[ -z "$refreshed_reason" ]]') < function_body.index(
        'mark_agentic_maintenance_ran "$reason"'
    )
    assert function_body.index('if [[ "$refreshed_reason" != "$reason" ]]') < function_body.index(
        'mark_agentic_maintenance_ran "$reason"'
    )


def test_supervisor_recovers_dirty_targets_before_agentic_maintenance():
    repo_root = Path(__file__).resolve().parents[4]
    script = (
        repo_root / "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh"
    ).read_text(encoding="utf-8")
    recovery_start = script.index("confirmed_dirty_target_reason() {")
    recovery_end = script.index("\nrun_agentic_maintenance() {", recovery_start)
    recovery_body = script[recovery_start:recovery_end]
    loop_start = script.index("while kill -0 \"$child_pid\"")
    dirty_reason_pos = script.index('dirty_recovery_reason="$(confirmed_dirty_target_reason || true)"', loop_start)
    maintenance_reason_pos = script.index('maintenance_reason="$(agentic_maintenance_reason || true)"', loop_start)

    assert "SUPERVISOR_DIRTY_TARGET_RECOVERY" in script
    assert '"dirty_target_recovery_enabled"' in script
    assert "recover_dirty_legal_parser_targets()" in recovery_body
    assert "dirty_recovery_committed" in recovery_body
    assert "dirty_recovery_restored" in recovery_body
    assert "pytest -q" in recovery_body
    assert "restore_legal_parser_targets_from_baseline_or_head" in script
    assert "snapshot_dirty_legal_parser_target_baseline()" in script
    assert "BASELINE_DIRTY_TARGET_MANIFEST_PATH" in script
    assert "BASELINE_DIRTY_TARGET_SNAPSHOT_DIR" in script
    assert "SUPERVISOR_DIRTY_TARGET_GRACE_SECONDS" in script
    assert "dirty_target_grace_seconds" in script
    assert '"requesting_llm_patch"' in recovery_body
    assert "dirty_legal_parser_targets_transient_phase" in recovery_body
    assert 'def restore_failed_dirty_targets(progress: dict, paths: list[str]) -> bool:' in recovery_body
    assert '"automatic restore failed"' in recovery_body
    assert "dirty_legal_parser_targets_known_bad_restore_failure" in recovery_body
    assert "and not known_bad_restore_failure" in recovery_body
    assert "status_stall_age < dirty_target_grace_seconds" in script
    assert dirty_reason_pos < maintenance_reason_pos


def test_supervisor_escalates_repeated_rejection_families_as_stuck_work():
    repo_root = Path(__file__).resolve().parents[4]
    script = (
        repo_root / "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh"
    ).read_text(encoding="utf-8")

    assert "SUPERVISOR_AGENTIC_REPEATED_REJECTION_FAMILY_TAIL" in script
    assert '"agentic_repeated_rejection_family_tail"' in script
    assert "SUPERVISOR_REPEATED_REJECTION_RECOVERY" in script
    assert '"repeated_rejection_recovery_enabled"' in script
    assert "def repeated_rejection_family(rejections: list[dict]) -> dict:" in script
    assert "def infer_legal_parser_targets(item: dict) -> list[str]:" in script
    assert "confirmed_repeated_rejection_dirty_target_reason()" in script
    assert "recover_repeated_rejection_dirty_targets()" in script
    assert "repeated rejection validation failed with rc=$rc; restoring only repeated rejection targets" in script
    assert 'restore_legal_parser_targets_from_baseline_or_head "$targets_file"' in script
    assert "repeated_rejection_family:" in script
    assert "repeated_rejection_family_count" in script
    assert "dirty_touched_file_rejections, or repeated_rejection_family" in script


def test_supervisor_stops_competing_automation_before_and_during_run():
    repo_root = Path(__file__).resolve().parents[4]
    script = (
        repo_root / "scripts/ops/legal_data/run_legal_parser_optimizer_daemon.sh"
    ).read_text(encoding="utf-8")
    function_start = script.index("terminate_competing_daemons() {")
    function_end = script.index("\nstop_child() {", function_start)
    function_body = script[function_start:function_end]

    assert 'SUPERVISOR_STOP_COMPETING_DAEMONS" != "1"' in function_body
    assert "tmux kill-session" in function_body
    assert "logic-port-daemon" in function_body
    assert "logic-port-daemon.service" in function_body
    assert "systemctl --user disable --now" in function_body
    assert "systemctl --user kill --signal=TERM" in function_body
    assert "SUPERVISOR_DISABLE_COMPETING_SYSTEMD_SERVICE" in function_body
    assert "ppd/daemon/ppd_daemon.py" in function_body
    assert "ipfs_datasets_py.optimizers.logic_port_daemon" in function_body
    assert script.index("terminate_matching_legal_parser_daemons") < script.index(
        "terminate_competing_daemons"
    )
    assert script.index("terminate_competing_daemons") < script.index("snapshot_dirty_legal_parser_target_baseline")
    assert script.index("snapshot_dirty_legal_parser_target_baseline") < script.index("while true; do")
    loop_start = script.index("while kill -0 \"$child_pid\"")
    assert loop_start < script.index("terminate_competing_daemons", loop_start)


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
    assert call["router_kwargs"]["sandbox"] == "read-only"


def test_optimizer_forces_codex_cli_generation_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_CODEX_SANDBOX", "workspace-write")
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
        provider="codex_cli",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)

    optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])

    assert fake_router.calls[0]["router_kwargs"]["sandbox"] == "read-only"
    assert fake_router.calls[0]["prompt"]
    assert __import__("os").environ["IPFS_DATASETS_PY_CODEX_SANDBOX"] == "workspace-write"


def test_optimizer_forces_default_codex_generation_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_CODEX_SANDBOX", "workspace-write")
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
        provider="llm_router",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)

    optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])

    assert fake_router.calls[0]["router_kwargs"]["provider"] is None
    assert fake_router.calls[0]["router_kwargs"]["provider_label"] == "llm_router"
    assert fake_router.calls[0]["router_kwargs"]["sandbox"] == "read-only"
    assert __import__("os").environ["IPFS_DATASETS_PY_CODEX_SANDBOX"] == "workspace-write"


def test_optimizer_restores_worktree_after_llm_side_effects(tmp_path):
    __import__("subprocess").run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    touched = tmp_path / "tracked.txt"
    touched.write_text("before\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)

    class _MutatingRouter:
        calls = []

        def generate(self, prompt, method, max_tokens=2000, temperature=0.7, router_kwargs=None):
            self.calls.append({"prompt": prompt, "router_kwargs": router_kwargs or {}})
            touched.write_text("after\n", encoding="utf-8")
            return json.dumps(
                {
                    "summary": "No-op patch for test.",
                    "requirements_addressed": [],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": "",
                }
            )

    router = _MutatingRouter()
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        model_name="gpt-5.5",
        provider="codex_cli",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=router)

    proposal = optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])

    assert proposal.summary == "No-op patch for test."
    assert touched.read_text(encoding="utf-8") == "before\n"
    assert __import__("subprocess").run(
        ["git", "diff", "--quiet"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    ).returncode == 0


def test_optimizer_tolerates_unrelated_restore_failure_when_legal_targets_clean(tmp_path, monkeypatch):
    __import__("subprocess").run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "No-op patch for test.",
                "requirements_addressed": [],
                "acceptance_criteria": ["proposal parsed despite unrelated restore warning"],
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
        provider="llm_router",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    monkeypatch.setattr(
        optimizer,
        "_restore_working_tree_diff",
        lambda _expected: {"valid": False, "reverse": {"stderr": "unrelated diff restore failed"}},
    )
    monkeypatch.setattr(
        optimizer,
        "_dirty_legal_parser_target_status",
        lambda: {
            "valid": True,
            "paths": [],
            "source": "test",
            "checked_at": "now",
            "fingerprint": "",
            "error": {},
        },
    )

    proposal = optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])

    assert proposal.summary == "No-op patch for test."


def test_optimizer_rejects_restore_failure_when_legal_targets_are_dirty(tmp_path, monkeypatch):
    __import__("subprocess").run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "No-op patch for test.",
                "requirements_addressed": [],
                "acceptance_criteria": ["should not be accepted"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": "",
            }
        )
    )
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    monkeypatch.setattr(optimizer, "_restore_working_tree_diff", lambda _expected: {"valid": False})
    monkeypatch.setattr(
        optimizer,
        "_dirty_legal_parser_target_status",
        lambda: {
            "valid": True,
            "paths": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "source": "test",
            "checked_at": "now",
            "fingerprint": "dirty",
            "error": {},
        },
    )

    try:
        optimizer.request_llm_patch(cycle_index=1, evaluation={"metrics": {}}, feedback=["gap"])
    except RuntimeError as exc:
        assert "changed legal-parser targets" in str(exc)
    else:
        raise AssertionError("expected legal target restore failure to raise")


def test_optimizer_scales_test_timeout_from_recent_suite_duration(tmp_path):
    out_dir = tmp_path / "out"
    cycle_dir = out_dir / "cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "tests": {
                    "valid": True,
                    "duration_seconds": 171.5,
                },
            }
        ),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=out_dir,
        test_timeout_seconds=180,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    assert optimizer.effective_test_timeout_seconds() == 403


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


def test_current_status_tracks_phase_age_separately_from_heartbeat_updates(tmp_path):
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)

    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
        proposal_attempt=1,
    )
    first = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    time.sleep(0.001)
    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
        proposal_attempt=1,
    )
    same_phase = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    time.sleep(0.001)
    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
        proposal_attempt=2,
    )
    next_attempt = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))

    assert first["phase_key"] == same_phase["phase_key"]
    assert same_phase["phase_started_at"] == first["phase_started_at"]
    assert same_phase["phase_updated_at"] > first["phase_updated_at"]
    assert next_attempt["phase_key"] != same_phase["phase_key"]
    assert next_attempt["phase_started_at"] > same_phase["phase_started_at"]


def test_current_status_exposes_phase_specific_stall_budget(tmp_path):
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        llm_timeout_seconds=900,
        test_timeout_seconds=600,
        heartbeat_interval_seconds=10,
        run_tests=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)

    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
    )
    llm_status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    daemon._write_current_status(
        status="running",
        phase="running_tests",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
    )
    test_status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))

    assert llm_status["phase_stale_after_seconds"] == 960
    assert llm_status["phase_stale_after_reason"] == "llm_timeout_seconds_plus_heartbeat_slack"
    assert test_status["phase_stale_after_seconds"] == 660
    assert test_status["phase_stale_after_reason"] == "effective_test_timeout_seconds_plus_heartbeat_slack"


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


def test_daemon_retries_candidate_that_fails_fast_post_apply_validation(tmp_path):
    (tmp_path / "x.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    invalid_diff = "\n".join(
        [
            "diff --git a/x.py b/x.py",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,2 +1,2 @@",
            " def value():",
            "-    return 1",
            "+    if depth  str:",
            "",
        ]
    )
    valid_diff = "\n".join(
        [
            "diff --git a/x.py b/x.py",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,2 +1,2 @@",
            " def value():",
            "-    return 1",
            "+    return 2",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "First patch compiles badly.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["candidate validation retries"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": invalid_diff,
                }
            ),
            json.dumps(
                {
                    "summary": "Second patch compiles.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["candidate validation passes"],
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
        apply_patches=True,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert cycle["proposal_attempts"][0]["retry_reason"].startswith(
        "candidate_post_apply_validation_failed:"
    )
    assert cycle["proposal_attempts"][0]["candidate_validation_valid"] is False
    assert "SyntaxError" in cycle["proposal_attempts"][0]["retry_reason"]
    assert cycle["proposal_attempts"][1]["candidate_validation_valid"] is True
    assert (tmp_path / "x.py").read_text(encoding="utf-8") == "def value():\n    return 2\n"
    assert "candidate_post_apply_validation_failed" in fake_router.calls[1]["prompt"]


def test_daemon_retries_candidate_that_fails_changed_test_preflight(tmp_path):
    test_path = "tests/unit_tests/logic/deontic/test_candidate_preflight.py"
    invalid_diff = "\n".join(
        [
            f"diff --git a/{test_path} b/{test_path}",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            f"+++ b/{test_path}",
            "@@ -0,0 +1,2 @@",
            "+def test_candidate_preflight():",
            "+    assert False",
            "",
        ]
    )
    valid_diff = "\n".join(
        [
            f"diff --git a/{test_path} b/{test_path}",
            "new file mode 100644",
            "index 0000000..2222222",
            "--- /dev/null",
            f"+++ b/{test_path}",
            "@@ -0,0 +1,2 @@",
            "+def test_candidate_preflight():",
            "+    assert True",
            "",
        ]
    )
    fake_router = _SequencedRouter(
        [
            json.dumps(
                {
                    "summary": "First patch has failing changed test.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["changed test preflight retries"],
                    "expected_metric_gain": {},
                    "tests_to_run": [],
                    "unified_diff": invalid_diff,
                }
            ),
            json.dumps(
                {
                    "summary": "Second patch fixes changed test.",
                    "requirements_addressed": ["daemon"],
                    "acceptance_criteria": ["changed test preflight passes"],
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
        apply_patches=True,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=2,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert len(fake_router.calls) == 2
    assert cycle["proposal_attempts"][0]["retry_reason"].startswith(
        "candidate_post_apply_validation_failed:"
    )
    assert "changed deontic tests failed focused pytest" in cycle["proposal_attempts"][0][
        "candidate_validation_reasons"
    ]
    assert cycle["proposal_attempts"][1]["candidate_validation_valid"] is True
    assert (tmp_path / test_path).read_text(encoding="utf-8").endswith("assert True\n")


def test_daemon_rejects_cycle_when_all_candidate_attempts_fail_validation(tmp_path):
    (tmp_path / "x.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    invalid_diff = "\n".join(
        [
            "diff --git a/x.py b/x.py",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,2 +1,2 @@",
            " def value():",
            "-    return 1",
            "+    if depth  str:",
            "",
        ]
    )
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Only candidate fails validation.",
                "requirements_addressed": ["daemon"],
                "acceptance_criteria": ["failed candidate is not applied"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": invalid_diff,
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=True,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
        llm_proposal_attempts=1,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=1)

    assert cycle["proposal_attempts"][0]["candidate_validation_valid"] is False
    assert cycle["patch_check"]["valid"] is False
    assert "all proposal attempts exhausted" in cycle["patch_check"]["stderr"]
    assert cycle["apply_result"]["applied"] is False
    assert cycle["apply_result"]["reason"] == "proposal_quality_failed"
    assert (tmp_path / "x.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"


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


def test_current_status_write_is_atomic_json(tmp_path):
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
        phase="checking_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-04-28T00:00:00+00:00",
    )

    status_text = (tmp_path / "out/current_status.json").read_text(encoding="utf-8")
    status = json.loads(status_text)

    assert status["phase"] == "checking_patch"
    assert not list((tmp_path / "out").glob(".current_status.json.*.tmp"))


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

    assert cycle["proposal_attempts"][0]["retry_reason"].startswith(
        "candidate_post_apply_validation_failed:"
    )
    assert cycle["proposal_attempts"][0]["candidate_validation_valid"] is False
    assert cycle["patch_check"]["valid"] is False
    assert "all proposal attempts exhausted" in cycle["patch_check"]["stderr"]
    assert cycle["apply_result"]["applied"] is False
    assert cycle["apply_result"]["reason"] == "proposal_quality_failed"
    assert cycle["post_apply_validation"]["reason"] == "patch_not_applied"
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


def test_progress_stall_accounting_resets_after_retained_patch(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycles = [
        {
            "cycle_index": 1,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "patch_check": {"valid": False},
            "apply_result": {"applied": False, "reason": "patch_check_failed"},
            "tests": {"valid": True},
        },
        {
            "cycle_index": 2,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "post_evaluation": {"metrics": {"parity_score": 0.9}},
            "patch_check": {"valid": True},
            "apply_result": {"applied": True},
            "tests": {"valid": True},
            "retained_change": {"has_retained_changes": True},
        },
        {
            "cycle_index": 3,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "patch_check": {"valid": False},
            "apply_result": {"applied": False, "reason": "patch_check_failed"},
            "tests": {"valid": True},
        },
    ]
    for cycle in cycles:
        cycle_dir = tmp_path / f"out/cycles/cycle_{cycle['cycle_index']:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(json.dumps(cycle), encoding="utf-8")

    progress = daemon._build_progress_summary(latest_cycle=cycles[-1])

    assert progress["stalled_metric_cycles"] == 1
    assert progress["cycles_since_meaningful_progress"] == 1
    assert progress["rolled_back_since_meaningful_progress"] == 0
    assert progress["rolled_back_reasons_since_meaningful_progress"] == {}
    assert "retained changes reset stall accounting" in progress["meaningful_progress_definition"]


def test_progress_summary_counts_rollback_reasons_since_meaningful_progress(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycles = [
        {
            "cycle_index": 1,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "post_evaluation": {"metrics": {"parity_score": 0.9}},
            "patch_check": {"valid": True},
            "apply_result": {"applied": True},
            "tests": {"valid": True},
            "retained_change": {"has_retained_changes": True},
        },
        {
            "cycle_index": 2,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "post_evaluation": {"metrics": {"parity_score": 0.9}},
            "patch_check": {"valid": True},
            "apply_result": {
                "applied": True,
                "rolled_back": True,
                "reason": "metric_stall_no_metric_progress",
            },
            "tests": {"valid": True},
        },
        {
            "cycle_index": 3,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "post_evaluation": {"metrics": {"parity_score": 0.9}},
            "patch_check": {"valid": True},
            "apply_result": {
                "applied": True,
                "rolled_back": True,
                "reason": "post_apply_validation_failed",
            },
            "tests": {"valid": False},
        },
    ]
    for cycle in cycles:
        cycle_dir = tmp_path / f"out/cycles/cycle_{cycle['cycle_index']:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(json.dumps(cycle), encoding="utf-8")

    progress = daemon._build_progress_summary(latest_cycle=cycles[-1])

    assert progress["rolled_back_count"] == 2
    assert progress["rolled_back_reason_counts"] == {
        "metric_stall_no_metric_progress": 1,
        "post_apply_validation_failed": 1,
    }
    assert progress["rolled_back_since_meaningful_progress"] == 2
    assert progress["rolled_back_reasons_since_meaningful_progress"] == {
        "metric_stall_no_metric_progress": 1,
        "post_apply_validation_failed": 1,
    }


def test_progress_summary_resets_stall_accounting_at_goal_epoch(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    daemon.run_started_at = "2026-05-01T10:00:00+00:00"
    cycles = [
        {
            "cycle_index": 1,
            "started_at": "2026-05-01T09:00:00+00:00",
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "patch_check": {"valid": True},
            "apply_result": {"applied": True, "rolled_back": True, "reason": "old_goal_failure"},
            "tests": {"valid": False},
        },
        {
            "cycle_index": 2,
            "started_at": "2026-05-01T10:01:00+00:00",
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "patch_check": {"valid": False, "stderr": "new goal rejected"},
            "apply_result": {"applied": False, "reason": "patch_check_failed"},
            "tests": {"valid": True},
        },
    ]
    for cycle in cycles:
        cycle_dir = tmp_path / f"out/cycles/cycle_{cycle['cycle_index']:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(json.dumps(cycle), encoding="utf-8")

    progress = daemon._build_progress_summary(latest_cycle=cycles[-1])

    assert progress["total_cycles"] == 2
    assert progress["goal_epoch_cycle_count"] == 1
    assert progress["rolled_back_count"] == 1
    assert progress["rolled_back_since_meaningful_progress"] == 0
    assert progress["cycles_since_meaningful_progress"] == 1
    assert progress["goal_epoch_rejected_patch_count"] == 1


def test_recent_cycle_history_uses_current_goal_epoch(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "current_run.json").write_text(
        json.dumps({"started_at": "2026-05-01T10:00:00+00:00"}),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=out_dir)
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    for index, started_at in [(1, "2026-05-01T09:00:00+00:00"), (2, "2026-05-01T10:01:00+00:00")]:
        cycle_dir = out_dir / f"cycles/cycle_{index:04d}"
        cycle_dir.mkdir(parents=True)
        (cycle_dir / "cycle_summary.json").write_text(
            json.dumps(
                {
                    "cycle_index": index,
                    "started_at": started_at,
                    "score": 0.9,
                    "patch_check": {"valid": False, "stderr": f"failure {index}"},
                    "apply_result": {"applied": False, "reason": "patch_check_failed"},
                    "tests": {"valid": True},
                }
            ),
            encoding="utf-8",
        )

    history = optimizer._recent_cycle_history(limit=5)

    assert [item["cycle_index"] for item in history] == [2]
    assert "failure 2" in history[0]["patch_failure_tail"]


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
    assert "do not add tests that assert an extracted legal fact should become empty" in prompt


def test_recent_cycle_history_summarizes_post_apply_validation_failures(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "score": 0.9763,
                "feedback": ["repair_required_count: 1"],
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {
                    "applied": True,
                    "rolled_back": True,
                    "reason": "post_apply_validation_failed",
                },
                "changed_files": [
                    "ipfs_datasets_py/logic/deontic/prover_syntax.py",
                    "tests/unit_tests/logic/deontic/test_deontic_prover_syntax.py",
                ],
                "post_apply_validation": {
                    "valid": False,
                    "compile": {
                        "valid": False,
                        "stderr": (
                            '  File "ipfs_datasets_py/logic/deontic/prover_syntax.py", line 194\n'
                            "    if depth  str:\n"
                            "              ^^^\n"
                            "SyntaxError: invalid syntax\n"
                        ),
                    },
                    "collect": {"valid": True, "skipped": True},
                    "reasons": ["changed Python files failed py_compile"],
                },
                "tests": {
                    "valid": False,
                    "skipped": True,
                    "reason": "post_apply_validation_failed",
                },
            }
        ),
        encoding="utf-8",
    )

    history = optimizer._recent_cycle_history(limit=1)
    recent_failures = optimizer._recent_test_failures(history)
    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert history[0]["post_apply_validation_valid"] is False
    assert "SyntaxError" in history[0]["validation_failure_summary"]["exception_types"]
    assert recent_failures[0]["failure_phase"] == "post_apply_validation"
    assert "prover_syntax.py" in recent_failures[0]["failure_head"]
    assert "py_compile" in recent_failures[0]["exception_types"]
    assert '"test_failure_recovery_mode": true' in prompt
    assert "compile-safe first" in prompt
    assert "SyntaxError" in prompt


def test_daemon_feeds_recent_failures_into_repair_phase_prompt(tmp_path):
    (tmp_path / "x.txt").write_text("before\n", encoding="utf-8")
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "score": 0.9763,
                "feedback": ["repair_required_count: 1"],
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {"applied": True, "rolled_back": True},
                "changed_files": ["ipfs_datasets_py/logic/deontic/prover_syntax.py"],
                "tests": {
                    "valid": False,
                    "stdout": "\n".join(
                        [
                            "E   AssertionError: expected time predicate",
                            "tests/unit_tests/logic/deontic/test_deontic_prover_syntax.py::test_target FAILED [ 90%]",
                            "FAILED tests/unit_tests/logic/deontic/test_deontic_prover_syntax.py::test_target - AssertionError",
                        ]
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
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
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Repair previous prover syntax failure.",
                "requirements_addressed": ["repair phase"],
                "acceptance_criteria": ["previous failure is repaired"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": valid_diff,
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=False,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    cycle = daemon.run_cycle(cycle_index=2)

    assert cycle["proposal_attempts"][0]["retry_reason"] == ""
    prompt = fake_router.calls[0]["prompt"]
    assert "repair_phase:" in prompt
    assert "repair_phase_failure:" in prompt
    assert "test_deontic_prover_syntax.py::test_target" in prompt
    assert "failed_tests=[," not in prompt
    assert "AssertionError" in prompt


def test_high_score_repair_prompt_requires_material_followthrough(tmp_path):
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(
        json.dumps(
            {
                "cycle_index": 1,
                "score": 0.9763,
                "feedback": ["repair_required_count: 1"],
                "patch_check": {"valid": True, "stderr": ""},
                "proposal_quality": {"valid": True, "reasons": []},
                "apply_result": {"applied": True, "rolled_back": True},
                "changed_files": [
                    "ipfs_datasets_py/logic/deontic/formula_builder.py",
                    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
                ],
                "post_apply_validation": {
                    "valid": False,
                    "compile": {"valid": True, "stderr": "", "stdout": ""},
                    "collect": {
                        "valid": False,
                        "stderr": "E   SyntaxError: invalid syntax",
                        "stdout": "FAILED tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
                    },
                    "focused_tests": {"valid": True, "stderr": "", "stdout": ""},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "out/progress_summary.json").write_text(
        json.dumps(
            {
                "current_score": 0.9763,
                "cycles_since_meaningful_progress": 1,
                "stalled_metric_cycles": 1,
                "accepted_change_summaries": [],
            }
        ),
        encoding="utf-8",
    )
    fake_router = _FakeRouter(
        json.dumps(
            {
                "summary": "Repair formula-builder collection failure with same-family followthrough.",
                "requirements_addressed": ["repair phase"],
                "acceptance_criteria": ["collection passes"],
                "expected_metric_gain": {},
                "tests_to_run": [],
                "unified_diff": "",
            }
        )
    )
    config = LegalParserDaemonConfig(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        apply_patches=False,
        run_tests=False,
        require_production_and_tests=False,
        require_clean_touched_files=False,
    )
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=fake_router)

    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert '"test_failure_recovery_mode": true' in prompt
    assert '"slice_scale_contract": {' in prompt
    assert '"mode": "repair_with_material_followthrough"' in prompt
    assert '"minimum_related_constructions": 2' in prompt
    assert '"target_focused_examples_or_assertions": "4-6"' in prompt
    assert "compile-safe first" in prompt


def test_daemon_rejects_source_grounded_mental_state_erasure_test(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config, optimizer=LegalParserParityOptimizer(daemon_config=config))
    proposal = LegalParserCycleProposal(
        summary="Bad mental state erasure test.",
        acceptance_criteria=["Reject contradictory slot erasure."],
        unified_diff="\n".join(
            [
                "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
                "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
                "@@",
                "+def test_bad_mental_state_erasure():",
                "+    text = 'A person shall knowingly submit a false statement.'",
                "+    norm = LegalNormIR.from_parser_element(extract_normative_elements(text)[0])",
                "+    assert norm.mental_state == \"\"",
            ]
        ),
    )

    quality = daemon._assess_proposal_quality(
        proposal,
        [
            "ipfs_datasets_py/logic/deontic/formula_builder.py",
            "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
        ],
    )

    assert quality["valid"] is False
    assert "tests must not assert empty mental_state" in quality["reasons"][-1]


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
    assert '"mode": "patch_stability_family"' in prompt
    assert '"minimum_related_constructions": 3' in prompt
    assert "single-phrase micro-patches are also rejected" in prompt
    assert '"recent_failed_patch_files": [' in prompt
    assert "prefer one production file plus one matching test file" in prompt


def test_optimizer_prompt_expands_slice_contract_when_metrics_are_stalled(tmp_path):
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
                "current_score": 0.976,
                "stalled_metric_cycles": 4,
                "cycles_since_meaningful_progress": 5,
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

    prompt = optimizer.build_patch_prompt(cycle_index=2, evaluation={"metrics": {}}, feedback=["gap"])

    assert '"slice_scale_contract": {' in prompt
    assert '"mode": "expanded_slice"' in prompt
    assert '"minimum_related_constructions": 3' in prompt
    assert '"target_focused_examples_or_assertions": "6-10"' in prompt
    assert "not one synonym, one predicate spelling, or a single narrow example" in prompt


def test_daemon_rejects_material_slice_that_is_too_small(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)
    quality = {"valid": True, "reasons": []}

    assessed = daemon._enforce_material_slice_quality(
        proposal_quality=quality,
        patch_stats={
            "insertions": 4,
            "deletions": 0,
            "changed_files": [
                "ipfs_datasets_py/logic/deontic/formula_builder.py",
                "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            ],
        },
        patch_stability_mode=False,
        slice_scale_mode="expanded_slice",
        test_failure_recovery_mode=False,
        material_slice_gate_active=True,
    )

    assert assessed["valid"] is False
    assert assessed["material_slice_quality"]["minimum_insertions"] == 30
    assert any("material_slice_too_small" in reason for reason in assessed["reasons"])


def test_daemon_rejects_too_small_high_score_repair_followthrough_slice(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=optimizer)

    assessed = daemon._enforce_material_slice_quality(
        proposal_quality={"valid": True, "reasons": []},
        patch_stats={
            "insertions": 10,
            "deletions": 2,
            "changed_files": [
                "ipfs_datasets_py/logic/deontic/formula_builder.py",
                "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            ],
        },
        patch_stability_mode=False,
        slice_scale_mode="repair_with_material_followthrough",
        test_failure_recovery_mode=True,
        material_slice_gate_active=True,
    )

    assert assessed["valid"] is False
    assert assessed["material_slice_quality"]["minimum_insertions"] == 24
    assert any("material_slice_too_small" in reason for reason in assessed["reasons"])


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
            "@@ -1 +1,10 @@",
            "-before_formula",
            "+after_formula",
            "+after_formula_notice",
            "+after_formula_appeal",
            "+after_formula_petition",
            "+after_formula_application",
            "+after_formula_remittance",
            "+after_formula_reimbursement",
            "+after_formula_processing",
            "+after_formula_publication",
            "+after_formula_mailing",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "@@ -1 +1,8 @@",
            "-before_test",
            "+after_test",
            "+after_test_notice",
            "+after_test_appeal",
            "+after_test_petition",
            "+after_test_application",
            "+after_test_remittance",
            "+after_test_reimbursement",
            "+after_test_processing",
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


def test_material_slice_gate_activates_for_expanded_and_repair_followthrough_modes(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(
        config=config,
        optimizer=LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}")),
    )

    assert daemon._material_slice_gate_active({"mode": "expanded_slice"}) is True
    assert daemon._material_slice_gate_active({"mode": "repair_with_material_followthrough"}) is True
    assert daemon._material_slice_gate_active({"mode": "repair_first"}) is False


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
                "rolled_back_reasons_since_meaningful_progress": {
                    "metric_stall_no_metric_progress": 4
                },
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
    assert "metric_stall_no_metric_progress" in prompt
    assert "cross_reference" in prompt
    assert "expected_metric_gain for a real metric" in prompt


def test_optimizer_prompt_marks_irreducible_residual_mode(tmp_path):
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
        json.dumps({"stalled_metric_cycles": 5, "current_feedback": ["repair_required_count: 1"]}),
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
            "metrics": {"parity_score": 0.9763, "coverage_gaps": ["repair_required_count: 1"]},
            "repair_required_details": [
                {
                    "sample_id": "cross_reference",
                    "source_id": "deontic:blocked",
                    "text": "The Secretary shall publish the notice except as provided in section 552.",
                    "parser_warnings": [
                        "cross_reference_requires_resolution",
                        "exception_requires_scope_review",
                    ],
                    "llm_repair": {"required": True, "deterministic_resolution": {}},
                }
            ],
        },
        feedback=["repair_required_count: 1"],
    )

    assert '"irreducible_residual_mode": true' in prompt
    assert "stop chasing repair_required_count" in prompt
    assert "deterministic_coverage" in prompt
    assert "Prioritize unresolved repair-required probes only when irreducible_residual_mode is false" in prompt


def test_optimizer_prompt_marks_roadmap_pivot_after_procedural_micro_patches(tmp_path):
    target_file = "ipfs_datasets_py/logic/deontic/exports.py"
    test_file = "tests/unit_tests/logic/deontic/test_deontic_exports.py"
    for path, body in {
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md": "Phase 8 encoder decoder prover syntax.",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md": "Implement reconstruction and prover syntax.",
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
                "stalled_metric_cycles": 50,
                "current_score": 0.9763,
                "accepted_change_summaries": [
                    {
                        "summary": "Add deterministic export coverage for docketing procedural triggers.",
                        "focus_area": "exports",
                    },
                    {
                        "summary": "Add deterministic export coverage for delivery trigger proof prerequisites.",
                        "focus_area": "exports",
                    },
                    {
                        "summary": "Add procedural timeline coverage for signature triggers.",
                        "focus_area": "formula",
                    },
                    {
                        "summary": "Add export coverage for recordkeeping procedure.event_relations.",
                        "focus_area": "exports",
                    },
                ],
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
        evaluation={"metrics": {"parity_score": 0.9763}, "repair_required_details": []},
        feedback=["repair_required_count: 1"],
    )

    assert '"roadmap_pivot_mode": true' in prompt
    assert "Phase 8 encoder/decoder/prover-syntax slice" in prompt
    assert "stop adding narrow procedural trigger/export variants" in prompt


def test_roadmap_pivot_activates_on_high_score_micro_patch_run_even_after_retained_change(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "progress_summary.json").write_text(
        json.dumps(
            {
                "stalled_metric_cycles": 0,
                "current_score": 0.9763,
                "accepted_change_summaries": [
                    {"summary": "Add procedural trigger export coverage.", "focus_area": "exports"},
                    {"summary": "Add proof prerequisite for procedure.event_relations.", "focus_area": "exports"},
                    {"summary": "Add procedural timeline trigger coverage.", "focus_area": "formula"},
                    {"summary": "Add another export coverage trigger.", "focus_area": "exports"},
                ],
            }
        ),
        encoding="utf-8",
    )
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=out_dir)
    optimizer = LegalParserParityOptimizer(daemon_config=config, llm_backend=_FakeRouter("{}"))

    assert optimizer._roadmap_pivot_mode(optimizer._progress_snapshot()) is True


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
            "@@ -1 +1,17 @@",
            "-before_parser",
            "+def parse_notice_trigger_family():",
            "+    cases = [",
            "+        'before_parser',",
            "+        'directive trigger notice',",
            "+        'directive trigger permit',",
            "+        'directive trigger hearing',",
            "+        'directive trigger filing',",
            "+        'directive trigger renewal',",
            "+        'directive trigger publication',",
            "+    ]",
            "+    return [case.upper() for case in cases]",
            "+",
            "+",
            "+def parse_notice_trigger_summary():",
            "+    return {'family': 'directive_trigger', 'count': 7}",
            "+",
            "+",
            "+def parse_notice_trigger_labels():",
            "+    return ['notice', 'permit', 'hearing', 'filing', 'renewal', 'publication']",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_converter.py b/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_converter.py",
            "@@ -1 +1,20 @@",
            "-before_test",
            "+def test_notice_trigger_family_examples():",
            "+    family = parse_notice_trigger_family()",
            "+    assert family[0] == 'BEFORE_PARSER'",
            "+    assert 'DIRECTIVE TRIGGER NOTICE' in family",
            "+    assert 'DIRECTIVE TRIGGER PERMIT' in family",
            "+    assert 'DIRECTIVE TRIGGER HEARING' in family",
            "+    assert 'DIRECTIVE TRIGGER FILING' in family",
            "+    assert 'DIRECTIVE TRIGGER RENEWAL' in family",
            "+    assert 'DIRECTIVE TRIGGER PUBLICATION' in family",
            "+",
            "+",
            "+def test_notice_trigger_summary():",
            "+    summary = parse_notice_trigger_summary()",
            "+    assert summary == {'family': 'directive_trigger', 'count': 7}",
            "+",
            "+",
            "+def test_notice_trigger_labels():",
            "+    labels = parse_notice_trigger_labels()",
            "+    assert labels == ['notice', 'permit', 'hearing', 'filing', 'renewal', 'publication']",
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
    assert "requires expected_metric_gain" in cycle["proposal_attempts"][0]["retry_reason"]
    assert "pivot away from clearing numbered references" in fake_router.calls[1]["prompt"]
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
            "@@ -1 +1,15 @@",
            "-EXPORT_MARKER = 'before_exports'",
            "+EXPORT_MARKER = 'after_exports'",
            "+EXPORT_CASES = [",
            "+    'repair_required_count',",
            "+    'proof_ready_rate',",
            "+    'cross_reference_resolution_rate',",
            "+    'phase8_quality_summary',",
            "+    'decoder_slot_loss',",
            "+    'ir_slot_provenance',",
            "+]",
            "+",
            "+",
            "+def export_metric_family_summary():",
            "+    return {'family': 'metric_summary', 'metrics': EXPORT_CASES, 'count': len(EXPORT_CASES)}",
            "+",
            "+",
            "+def export_metric_names():",
            "+    return ','.join(EXPORT_CASES)",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_exports.py b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "@@ -1,2 +1,18 @@",
            " def test_marker():",
            "-    assert 'before_test'",
            "+    assert 'after_test'",
            "+",
            "+",
            "+def test_export_metric_family_summary():",
            "+    summary = {'family': 'metric_summary', 'metrics': ['repair_required_count', 'proof_ready_rate', 'cross_reference_resolution_rate', 'phase8_quality_summary', 'decoder_slot_loss', 'ir_slot_provenance'], 'count': 6}",
            "+    assert summary['family'] == 'metric_summary'",
            "+    assert summary['count'] == 6",
            "+    assert 'repair_required_count' in summary['metrics']",
            "+    assert 'proof_ready_rate' in summary['metrics']",
            "+    assert 'cross_reference_resolution_rate' in summary['metrics']",
            "+    assert 'phase8_quality_summary' in summary['metrics']",
            "+",
            "+",
            "+def test_export_metric_names():",
            "+    names = 'repair_required_count,proof_ready_rate,cross_reference_resolution_rate,phase8_quality_summary,decoder_slot_loss,ir_slot_provenance'",
            "+    assert 'repair_required_count' in names",
            "+    assert 'ir_slot_provenance' in names",
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
            "@@ -1 +1,15 @@",
            "-before_exports",
            "+def export_only_summary_rows():",
            "+    return [",
            "+        'after_exports',",
            "+        'repair_required_count',",
            "+        'proof_ready_rate',",
            "+        'cross_reference_resolution_rate',",
            "+        'phase8_quality_summary',",
            "+        'decoder_slot_loss',",
            "+        'ir_slot_provenance',",
            "+    ]",
            "+",
            "+",
            "+def export_only_summary_count():",
            "+    return len(export_only_summary_rows())",
            "+",
            "+",
            "+def export_only_summary_labels():",
            "+    return ['exports', 'metrics', 'phase8']",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_exports.py b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_exports.py",
            "@@ -1 +1,18 @@",
            "-before_exports_test",
            "+def test_export_only_summary_rows():",
            "+    rows = export_only_summary_rows()",
            "+    assert rows[0] == 'after_exports'",
            "+    assert 'repair_required_count' in rows",
            "+    assert 'proof_ready_rate' in rows",
            "+    assert 'cross_reference_resolution_rate' in rows",
            "+    assert 'phase8_quality_summary' in rows",
            "+    assert 'decoder_slot_loss' in rows",
            "+    assert 'ir_slot_provenance' in rows",
            "+",
            "+",
            "+def test_export_only_summary_count():",
            "+    assert export_only_summary_count() == 7",
            "+",
            "+",
            "+def test_export_only_summary_labels():",
            "+    assert export_only_summary_labels() == ['exports', 'metrics', 'phase8']",
            "",
        ]
    )
    formula_diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/formula_builder.py b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "--- a/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "+++ b/ipfs_datasets_py/logic/deontic/formula_builder.py",
            "@@ -1 +1,15 @@",
            "-before_formula",
            "+def formula_family_summary():",
            "+    return [",
            "+        'after_formula',",
            "+        'abatement duty',",
            "+        'mitigation duty',",
            "+        'remediation duty',",
            "+        'publication duty',",
            "+        'notice duty',",
            "+        'hearing duty',",
            "+    ]",
            "+",
            "+",
            "+def formula_family_count():",
            "+    return len(formula_family_summary())",
            "+",
            "+",
            "+def formula_family_labels():",
            "+    return ['abatement', 'mitigation', 'remediation', 'publication', 'notice', 'hearing']",
            "diff --git a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "--- a/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "+++ b/tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
            "@@ -1 +1,18 @@",
            "-before_formula_test",
            "+def test_formula_family_summary():",
            "+    examples = formula_family_summary()",
            "+    assert examples[0] == 'after_formula'",
            "+    assert 'abatement duty' in examples",
            "+    assert 'mitigation duty' in examples",
            "+    assert 'remediation duty' in examples",
            "+    assert 'publication duty' in examples",
            "+    assert 'notice duty' in examples",
            "+    assert 'hearing duty' in examples",
            "+",
            "+",
            "+def test_formula_family_count():",
            "+    assert formula_family_count() == 7",
            "+",
            "+",
            "+def test_formula_family_labels():",
            "+    assert formula_family_labels() == ['abatement', 'mitigation', 'remediation', 'publication', 'notice', 'hearing']",
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


def test_roadmap_pivot_quality_rejects_more_procedural_trigger_exports(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(
        summary="Add deterministic export coverage for another procedural trigger proof prerequisite.",
        requirements_addressed=["procedural timeline export coverage"],
        acceptance_criteria=["procedure.event_relations classify a new triggered_by_foo_of relation"],
        expected_metric_gain={"coverage_expansion": "procedural trigger export coverage"},
    )
    quality = {"valid": True, "reasons": []}

    result = daemon._enforce_roadmap_pivot_quality(
        proposal=proposal,
        proposal_quality=quality,
        changed_files=[
            "ipfs_datasets_py/logic/deontic/exports.py",
            "tests/unit_tests/logic/deontic/test_deontic_exports.py",
        ],
    )

    assert result["valid"] is False
    assert result["roadmap_pivot_mode"] is True
    assert any("procedural-trigger/export synonym" in reason for reason in result["reasons"])


def test_roadmap_pivot_quality_allows_phase8_prover_syntax_slice(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(
        summary="Add local theorem-prover syntax validation for LegalNormIR exports.",
        requirements_addressed=["Phase 8 prover syntax"],
        acceptance_criteria=["frame logic and deontic temporal first-order logic syntax checks run"],
        expected_metric_gain={"prover_syntax_coverage": "local logic stack syntax validation"},
    )
    quality = {"valid": True, "reasons": []}

    result = daemon._enforce_roadmap_pivot_quality(
        proposal=proposal,
        proposal_quality=quality,
        changed_files=[
            "ipfs_datasets_py/logic/deontic/prover_syntax.py",
            "tests/unit_tests/logic/deontic/test_deontic_prover_syntax.py",
        ],
    )

    assert result["valid"] is True


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


def test_metric_stall_retention_allows_coverage_gain_for_irreducible_residual(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    proposal = LegalParserCycleProposal(expected_metric_gain={"deterministic_coverage": "new parser case"})

    result = daemon._metric_stall_retention_result(
        proposal=proposal,
        evaluation={"metrics": {"parity_score": 0.9763, "repair_required_count": 1}},
        post_evaluation={"metrics": {"parity_score": 0.9763, "repair_required_count": 1}},
        metric_stall_mode=True,
        irreducible_residual_mode=True,
    )

    assert result["valid"] is True
    assert result["accepted_without_metric_delta"] is True
    assert "irreducible" in result["reasons"][0]


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


def test_dirty_touched_files_reports_rename_destination(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    old_path = repo / "ipfs_datasets_py/logic/deontic/old.py"
    old_path.parent.mkdir(parents=True)
    old_path.write_text("before\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(
        [
            "git",
            "mv",
            "ipfs_datasets_py/logic/deontic/old.py",
            "ipfs_datasets_py/logic/deontic/new.py",
        ],
        cwd=repo,
        check=True,
    )
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    dirty = daemon._dirty_touched_files(["ipfs_datasets_py/logic/deontic/new.py"])

    assert dirty == ["ipfs_datasets_py/logic/deontic/new.py"]


def test_git_status_porcelain_paths_deduplicate_and_use_rename_destination():
    paths = _paths_from_git_status_porcelain(
        "\n".join(
            [
                " M ipfs_datasets_py/logic/deontic/formula_builder.py",
                "M  ipfs_datasets_py/logic/deontic/formula_builder.py",
                "R  ipfs_datasets_py/logic/deontic/old.py -> ipfs_datasets_py/logic/deontic/new.py",
            ]
        )
    )

    assert paths == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py",
        "ipfs_datasets_py/logic/deontic/new.py",
    ]


def test_current_status_exposes_dirty_legal_parser_targets(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    target = repo / "ipfs_datasets_py/logic/deontic/formula_builder.py"
    maintenance_test = repo / "tests/unit_tests/logic/deontic/test_legal_parser_optimizer_daemon.py"
    unrelated = repo / "scripts/ops/legal_data/run_logic_port_daemon.sh"
    target.parent.mkdir(parents=True)
    maintenance_test.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    maintenance_test.write_text("before\n", encoding="utf-8")
    unrelated.write_text("before\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    target.write_text("after\n", encoding="utf-8")
    maintenance_test.write_text("after\n", encoding="utf-8")
    unrelated.write_text("after\n", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle_dir = repo / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)

    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
    )
    status = json.loads((repo / "out/current_status.json").read_text(encoding="utf-8"))
    progress = daemon._build_progress_summary(
        latest_cycle={
            "cycle_index": 1,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "apply_result": {"applied": False, "reason": "apply_patches_disabled"},
            "patch_check": {"valid": False},
            "tests": {"valid": True},
        }
    )

    assert status["dirty_legal_parser_targets"] == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py"
    ]
    assert progress["dirty_legal_parser_targets"] == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py"
    ]
    assert status["dirty_legal_parser_targets_valid"] is True
    assert status["dirty_legal_parser_targets_error"] == {}
    assert status["dirty_legal_parser_targets_source"] == "fresh_git_status_porcelain"
    assert status["dirty_legal_parser_targets_checked_at"]
    assert status["dirty_legal_parser_targets_fingerprint"]
    assert progress["dirty_legal_parser_targets_valid"] is True
    assert progress["dirty_legal_parser_targets_error"] == {}
    assert progress["dirty_legal_parser_targets_source"] == "fresh_git_status_porcelain"
    assert progress["dirty_legal_parser_targets_checked_at"]
    assert progress["dirty_legal_parser_targets_fingerprint"] == status[
        "dirty_legal_parser_targets_fingerprint"
    ]


def test_current_status_exposes_dirty_target_detection_failure(tmp_path, monkeypatch):
    def fake_run_command(*args, **kwargs):
        return {
            "valid": False,
            "returncode": 128,
            "stdout": "",
            "stderr": "fatal: not a git repository",
        }

    monkeypatch.setattr(parser_daemon_module, "_run_command", fake_run_command)
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle_dir = tmp_path / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)

    daemon._write_current_status(
        status="running",
        phase="requesting_llm_patch",
        cycle_index=1,
        cycle_dir=cycle_dir,
        started_at="2026-05-01T00:00:00+00:00",
    )
    status = json.loads((tmp_path / "out/current_status.json").read_text(encoding="utf-8"))
    progress = daemon._build_progress_summary(
        latest_cycle={
            "cycle_index": 1,
            "score": 0.9,
            "metrics": {"parity_score": 0.9},
            "apply_result": {"applied": False, "reason": "apply_patches_disabled"},
            "patch_check": {"valid": False},
            "tests": {"valid": True},
        }
    )

    assert status["dirty_legal_parser_targets"] == []
    assert status["dirty_legal_parser_targets_valid"] is False
    assert status["dirty_legal_parser_targets_error"]["returncode"] == 128
    assert "not a git repository" in status["dirty_legal_parser_targets_error"]["stderr_tail"]
    assert status["dirty_legal_parser_targets_source"] == "fresh_git_status_porcelain"
    assert status["dirty_legal_parser_targets_checked_at"]
    assert status["dirty_legal_parser_targets_fingerprint"] == ""
    assert progress["dirty_legal_parser_targets_valid"] is False
    assert progress["dirty_legal_parser_targets_source"] == "fresh_git_status_porcelain"
    assert progress["dirty_legal_parser_targets_fingerprint"] == ""


def test_dirty_legal_parser_target_fingerprint_changes_with_untracked_content(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    tracked = repo / "README.md"
    tracked.write_text("tracked\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    target = repo / "ipfs_datasets_py/logic/deontic/formula_builder.py"
    target.parent.mkdir(parents=True)
    target.write_text("first\n", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    first = daemon._dirty_legal_parser_target_status()
    target.write_text("second\n", encoding="utf-8")
    second = daemon._dirty_legal_parser_target_status()

    assert first["paths"] == ["ipfs_datasets_py/logic/deontic/formula_builder.py"]
    assert second["paths"] == first["paths"]
    assert first["fingerprint"]
    assert second["fingerprint"]
    assert second["fingerprint"] != first["fingerprint"]


def test_progress_report_lists_dirty_legal_parser_recovery_targets(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    report = daemon._format_progress_report(
        {
            "dirty_legal_parser_targets": [
                "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py"
            ],
            "git_retained_work": {},
            "run": {},
        }
    )

    assert "Dirty legal-parser recovery targets:" in report
    assert "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py" in report


def test_progress_report_lists_dirty_target_detection_failure(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())

    report = daemon._format_progress_report(
        {
            "dirty_legal_parser_targets_valid": False,
            "dirty_legal_parser_targets_error": {
                "returncode": 128,
                "stderr_tail": "fatal: not a git repository",
            },
            "git_retained_work": {},
            "run": {},
        }
    )

    assert "Dirty legal-parser target detection failed:" in report
    assert "returncode: `128`" in report
    assert "fatal: not a git repository" in report


def test_progress_summary_exposes_active_dirty_touched_rejection_files(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    target = repo / "ipfs_datasets_py/logic/deontic/formula_builder.py"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    target.write_text("stranded\n", encoding="utf-8")
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle = {
        "cycle_index": 1,
        "score": 0.9,
        "metrics": {"parity_score": 0.9},
        "patch_check": {"valid": False},
        "proposal_quality": {
            "valid": False,
            "reasons": [
                "patch touches files with pre-existing uncommitted changes: "
                "ipfs_datasets_py/logic/deontic/formula_builder.py"
            ],
            "dirty_touched_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
        },
        "apply_result": {"applied": False, "reason": "proposal_quality_failed"},
        "tests": {"valid": True},
    }
    cycle_dir = repo / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(json.dumps(cycle), encoding="utf-8")

    progress = daemon._build_progress_summary(latest_cycle=cycle)

    assert progress["dirty_touched_file_rejection_count"] == 1
    assert progress["active_dirty_touched_files"] == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py"
    ]
    assert progress["recent_rejections"][0]["dirty_touched_files"] == [
        "ipfs_datasets_py/logic/deontic/formula_builder.py"
    ]


def test_progress_summary_does_not_report_stale_dirty_rejection_files_as_active(tmp_path):
    repo = tmp_path
    __import__("subprocess").run(["git", "init"], cwd=repo, check=True, capture_output=True)
    __import__("subprocess").run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    __import__("subprocess").run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    target = repo / "ipfs_datasets_py/logic/deontic/formula_builder.py"
    target.parent.mkdir(parents=True)
    target.write_text("clean\n", encoding="utf-8")
    __import__("subprocess").run(["git", "add", "."], cwd=repo, check=True)
    __import__("subprocess").run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    config = LegalParserDaemonConfig(repo_root=repo, output_dir=repo / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    cycle = {
        "cycle_index": 1,
        "score": 0.9,
        "metrics": {"parity_score": 0.9},
        "patch_check": {"valid": False},
        "proposal_quality": {
            "valid": False,
            "reasons": [
                "patch touches files with pre-existing uncommitted changes: "
                "ipfs_datasets_py/logic/deontic/formula_builder.py"
            ],
            "dirty_touched_files": ["ipfs_datasets_py/logic/deontic/formula_builder.py"],
        },
        "apply_result": {"applied": False, "reason": "proposal_quality_failed"},
        "tests": {"valid": True},
    }
    cycle_dir = repo / "out/cycles/cycle_0001"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle_summary.json").write_text(json.dumps(cycle), encoding="utf-8")

    progress = daemon._build_progress_summary(latest_cycle=cycle)

    assert progress["dirty_touched_file_rejection_count"] == 1
    assert progress["active_dirty_touched_files"] == []


def test_progress_report_names_visible_commits_and_uncommitted_files(tmp_path):
    config = LegalParserDaemonConfig(repo_root=tmp_path, output_dir=tmp_path / "out")
    daemon = LegalParserOptimizerDaemon(config=config, optimizer=_FailingOptimizer())
    progress = {
        "updated_at": "2026-04-28T00:00:00+00:00",
        "run": {"run_id": "run-1", "baseline_head": "abc123"},
        "total_cycles": 3,
        "retained_accepted_patch_count": 1,
        "rolled_back_count": 1,
        "rolled_back_since_meaningful_progress": 1,
        "rolled_back_reasons_since_meaningful_progress": {"metric_stall_no_metric_progress": 1},
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
    assert "metric_stall_no_metric_progress" in report
    assert "repair_required_count: 1" in report
    assert "patch_check_failed:error: patch failed" in report

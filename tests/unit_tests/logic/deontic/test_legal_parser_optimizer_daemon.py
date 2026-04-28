"""Tests for the deterministic legal parser optimizer daemon."""

import json

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


class _FailingOptimizer:
    def generate(self, input_data, context):
        raise RuntimeError("boom before proposal")


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
    assert progress_payload["latest_cycle"]["changed_files"] == cycle["changed_files"]

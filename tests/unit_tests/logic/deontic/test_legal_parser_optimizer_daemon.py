"""Tests for the deterministic legal parser optimizer daemon."""

import json

from ipfs_datasets_py.optimizers.logic.deontic.parser_daemon import (
    LegalParserDaemonConfig,
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


def test_parse_cycle_proposal_accepts_strict_json():
    raw = json.dumps(
        {
            "summary": "Add deterministic coverage.",
            "requirements_addressed": ["Phase 4"],
            "expected_metric_gain": {"parsed_rate": 0.1},
            "tests_to_run": ["pytest tests/unit_tests/logic/deontic"],
            "unified_diff": "diff --git a/x b/x\n",
        }
    )

    proposal = parse_cycle_proposal(raw)

    assert proposal.summary == "Add deterministic coverage."
    assert proposal.requirements_addressed == ["Phase 4"]
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
    assert (repo_root / "out/latest_summary.json").exists()

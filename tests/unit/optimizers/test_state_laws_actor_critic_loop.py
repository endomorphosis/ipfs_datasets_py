import json
from pathlib import Path

from ipfs_datasets_py.optimizers.agentic.state_laws_actor_critic_loop import (
    ActorPolicyConfig,
    LoopConfig,
    StateLawsActorCriticLoop,
    TrialOutcome,
)


def _make_loop() -> StateLawsActorCriticLoop:
    return StateLawsActorCriticLoop(
        states=["OK", "IN", "LA"],
        loop_config=LoopConfig(target_score=0.9, actors_per_round=3, max_rounds=2),
    )


def test_critic_score_prefers_healthy_diagnostics():
    loop = _make_loop()

    healthy = {
        "coverage": {
            "states_targeted": 3,
            "states_with_nonzero_statutes": 3,
            "coverage_gap_states": [],
        },
        "fetch": {
            "success_ratio": 0.9,
            "no_attempt_states": [],
            "weak_states": [],
        },
        "etl_readiness": {
            "ready_for_kg_etl": True,
            "full_text_ratio": 1.0,
            "jsonld_ratio": 0.95,
            "citation_ratio": 0.8,
        },
        "quality": {"weak_states": []},
    }

    weak = {
        "coverage": {
            "states_targeted": 3,
            "states_with_nonzero_statutes": 1,
            "coverage_gap_states": ["IN", "LA"],
        },
        "fetch": {
            "success_ratio": 0.2,
            "no_attempt_states": ["IN", "LA"],
            "weak_states": [{"state": "OK", "scaffold_ratio": 0.0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0}],
        },
        "etl_readiness": {
            "ready_for_kg_etl": False,
            "full_text_ratio": 0.4,
            "jsonld_ratio": 0.2,
            "citation_ratio": 0.1,
        },
        "quality": {
            "weak_states": [
                {"state": "OK", "scaffold_ratio": 0.6, "nav_like_ratio": 0.2, "fallback_section_ratio": 0.2}
            ]
        },
    }

    assert loop._critic_score(healthy) > loop._critic_score(weak)


def test_recommend_patch_targets_includes_state_specific_scrapers():
    loop = _make_loop()
    diagnostics = {
        "coverage": {"coverage_gap_states": ["OK"]},
        "fetch": {"no_attempt_states": ["IN"], "weak_states": [{"state": "LA"}]},
        "quality": {"weak_states": [{"state": "OK"}]},
        "etl_readiness": {},
    }

    targets = loop._recommend_patch_targets(diagnostics)

    assert "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py" in targets
    assert "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py" in targets
    assert "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/indiana.py" in targets
    assert "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/louisiana.py" in targets


def test_mutation_prioritizes_resilience_when_no_attempt_states():
    loop = _make_loop()

    best = TrialOutcome(
        round_index=1,
        actor_name="baseline",
        config={
            "name": "baseline",
            "parallel_workers": 6,
            "per_state_retry_attempts": 1,
            "rate_limit_delay": 1.0,
            "min_full_text_chars": 300,
            "hydrate_statute_text": True,
        },
        status="partial_success",
        critic_score=0.5,
        diagnostics={
            "fetch": {"no_attempt_states": ["OK"], "weak_states": []},
            "etl_readiness": {"ready_for_kg_etl": False},
            "quality": {"weak_states": []},
        },
        passed=False,
    )

    mutated = loop._mutate_from_best(best)

    names = [cfg.name for cfg in mutated]
    assert "resilience_retry" in names
    resilience = [cfg for cfg in mutated if cfg.name == "resilience_retry"][0]
    assert isinstance(resilience, ActorPolicyConfig)
    assert resilience.per_state_retry_attempts >= 2


def test_build_patch_plan_ranks_state_files_with_reasons():
    loop = _make_loop()

    outcomes = [
        TrialOutcome(
            round_index=1,
            actor_name="a1",
            config={
                "name": "a1",
                "parallel_workers": 6,
                "per_state_retry_attempts": 1,
                "rate_limit_delay": 1.0,
                "min_full_text_chars": 300,
                "hydrate_statute_text": True,
            },
            status="partial_success",
            critic_score=0.35,
            diagnostics={
                "coverage": {"coverage_gap_states": ["OK"]},
                "fetch": {"no_attempt_states": ["IN"], "weak_states": [{"state": "LA"}]},
                "quality": {"weak_states": [{"state": "OK"}]},
                "etl_readiness": {"ready_for_kg_etl": False},
            },
            passed=False,
            recommended_patch_targets=[
                "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
                "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
                "ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py",
                "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py",
            ],
        )
    ]

    plan = loop._build_patch_plan(outcomes)

    assert len(plan) > 0
    paths = [item["path"] for item in plan]
    assert "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py" in paths
    ok_entry = [item for item in plan if item["path"].endswith("oklahoma.py")][0]
    assert "OK" in ok_entry["states"]
    assert "coverage_gap" in ok_entry["reasons"] or "quality_weak" in ok_entry["reasons"]


def test_build_apply_patch_tasks_respects_limit_and_actions():
    loop = _make_loop()
    patch_plan = [
        {
            "path": "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py",
            "priority_score": 0.9,
            "reasons": ["fetch_no_attempt", "quality_weak"],
            "states": ["OK"],
        },
        {
            "path": "ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py",
            "priority_score": 0.7,
            "reasons": ["etl_not_ready"],
            "states": [],
        },
    ]

    tasks = loop._build_apply_patch_tasks(patch_plan, limit=1)

    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "patch-task-001"
    assert tasks[0]["path"].endswith("oklahoma.py")
    joined_actions = " ".join(tasks[0]["suggested_actions"])
    assert "zero hydration attempts" in joined_actions or "no hydration attempts" in joined_actions


def test_execute_apply_plan_builds_queue_and_prechecks(tmp_path: Path):
    loop = _make_loop()
    loop.run_dir = tmp_path

    target_file = Path("ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py")
    tasks_file = tmp_path / "tasks.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps({"task_id": "patch-task-001", "path": str(target_file), "reasons": ["etl_not_ready"], "states": []}),
                json.dumps({"task_id": "patch-task-002", "path": "ipfs_datasets_py/does_not_exist.py", "reasons": [], "states": []}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = loop._execute_apply_plan(tasks_file, max_tasks=2)

    assert report["selected_count"] == 2
    assert "execution_queue_jsonl" in report
    assert Path(report["execution_queue_jsonl"]).exists()
    assert any(item["status"] == "ready_for_patch" for item in report["items"])
    assert any(item["status"] == "blocked" for item in report["items"])


def test_run_auto_patch_dry_run_skips_with_reason():
    loop = _make_loop()
    execution_report = {
        "items": [
            {
                "status": "ready_for_patch",
                "path": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            }
        ]
    }

    report = loop._run_auto_patch(execution_report, max_tasks=1, dry_run=True)

    assert report["dry_run"] is True
    assert report["selected_ready_tasks"] == 1
    assert report["applied_count"] == 0
    assert report["skipped_count"] == 1
    assert report["attempts"][0]["status"] == "skipped"
    assert str(report["attempts"][0]["reason"]).startswith("dry-run:")


def test_apply_text_strategy_normalizes_wayback_scheme_to_http():
    loop = _make_loop()
    original = (
        "seed = 'https://web.archive.org/web/20200101010101/https://example.gov/path'\n"
        "other = 'https://example.org/no-change'\n"
    )

    updated = loop._apply_text_strategy(original, "normalize-wayback-scheme-http")

    assert "http://web.archive.org/web/20200101010101/https://example.gov/path" in updated
    assert "https://example.org/no-change" in updated


def test_resolve_auto_patch_strategy_prefers_wayback_for_state_scrapers():
    loop = _make_loop()

    strategy = loop._resolve_auto_patch_strategy(
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py"
    )

    assert strategy == "normalize-wayback-scheme-http"


def test_resolve_auto_patch_strategy_respects_allow_and_deny_policies():
    loop = StateLawsActorCriticLoop(
        states=["OK"],
        loop_config=LoopConfig(
            max_rounds=1,
            auto_patch_allow_globs=["ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py"],
            auto_patch_deny_globs=["*state_laws_scraper.py"],
            wayback_allow_globs=["*oklahoma.py"],
            wayback_deny_globs=["*hawaii.py"],
        ),
    )

    assert (
        loop._resolve_auto_patch_strategy(
            "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py"
        )
        == "normalize-wayback-scheme-http"
    )
    assert (
        loop._resolve_auto_patch_strategy(
            "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py"
        )
        is None
    )
    assert (
        loop._resolve_auto_patch_strategy(
            "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/hawaii.py"
        )
        is None
    )


def test_auto_patch_reports_policy_block_reason():
    loop = StateLawsActorCriticLoop(
        states=["OK"],
        loop_config=LoopConfig(max_rounds=1, auto_patch_allow_globs=["*oklahoma.py"]),
    )

    result = loop._auto_patch_single(
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/indiana.py",
        dry_run=True,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "blocked-by-auto-patch-policy"
    policy = result.get("policy") or {}
    assert policy.get("allowed") is False
    assert policy.get("matched_allow_globs") == []


def test_auto_patch_includes_policy_preview_on_dry_run():
    loop = StateLawsActorCriticLoop(
        states=["OK"],
        loop_config=LoopConfig(max_rounds=1, auto_patch_allow_globs=["*oklahoma.py"]),
    )

    result = loop._auto_patch_single(
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/oklahoma.py",
        dry_run=True,
    )

    assert result["status"] == "skipped"
    assert str(result["reason"]).startswith("dry-run:")
    policy = result.get("policy") or {}
    assert policy.get("allowed") is True
    assert policy.get("matched_allow_globs") == ["*oklahoma.py"]

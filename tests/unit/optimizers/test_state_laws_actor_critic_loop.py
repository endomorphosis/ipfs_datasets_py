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

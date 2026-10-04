"""Selection cannot exchange old task retention for a new authored score."""
from copy import deepcopy

import pytest

from scripts.ops.legal_ir import run_legal_role_curriculum_experiment as runner


def metrics(steps=200, new=60):
    result = {key: (0 if "unsupported" in key else maximum // 2) for key, maximum in runner.metric_keys().items()}
    return result | {"steps": steps, "tuning_new_exact": new}


@pytest.mark.parametrize("key", ["tuning_earlier_exact", "tuning_temporal_exact", "tuning_prior_consistency_exact",
                                "tuning_document_parent_exact", "tuning_document_expanded_exact"])
def test_every_retention_gate_is_required_and_exact_one_case_tolerance_applies(key):
    parent, early, late = metrics(new=10), metrics(), metrics(400, 95)
    late[key] = parent[key] - 2
    assert runner.select_stage([early, late], parent) is early
    late[key] = parent[key] - 1
    assert runner.select_stage([early, late], parent) is late


@pytest.mark.parametrize("policy", ["parent", "expanded"])
def test_any_unsupported_document_acceptance_refuses_candidate(policy):
    parent, early, late = metrics(), metrics(), metrics(400, 96)
    early[f"tuning_document_{policy}_unsupported_accepted"] = 1
    late[f"tuning_document_{policy}_unsupported_accepted"] = 1
    assert runner.select_stage([early, late], parent) is None


def test_tuning_rank_and_earliest_stage_are_deterministic():
    parent, early, late = metrics(), metrics(), metrics(400)
    assert runner.select_stage([late, early], parent) is early
    late["tuning_temporal_exact"] += 1
    assert runner.select_stage([late, early], parent) is late
    early["tuning_new_exact"] += 1
    assert runner.select_stage([late, early], parent) is early


@pytest.mark.parametrize("change", ["missing", "bool", "overflow", "wrong_steps"])
def test_incomplete_or_malformed_metrics_cannot_select(change):
    parent, stages = metrics(), [metrics(), metrics(400)]
    if change == "missing": stages[0].pop("tuning_prior_consistency_exact")
    elif change == "bool": stages[0]["tuning_new_exact"] = True
    elif change == "overflow": stages[0]["tuning_new_exact"] = 97
    else: stages[0]["steps"] = 100
    with pytest.raises((ValueError, KeyError)):
        runner.select_stage(stages, parent)


def test_fallback_controls_and_both_fixed_boundaries_keep_all_model_slots():
    parents, trials = {}, []
    for architecture in runner.ARCHITECTURES:
        for seed in runner.SEEDS:
            checkpoint = {"path": f"/{architecture}-{seed}", "sha256": str(seed)}
            parents[(architecture, seed)] = {"checkpoint": checkpoint}
            trials.append({"name": f"role_curriculum_{architecture}-{seed}", "arm": f"role_curriculum_{architecture}",
                "objective": "role_curriculum", "architecture": architecture, "seed": seed,
                "enabled": architecture == "grounding", "parent": checkpoint, "checkpoint": checkpoint,
                "decoder_kind": "consistency", "executed_steps": 400, "selected_steps": 0,
                "selection": "parent_fallback_no_acceptable_replacement"})
    models, pipelines = runner.model_inventory(trials, parents)
    assert len(models) == 12 and len(pipelines) == 24
    assert len({row["name"] for row in pipelines}) == 24
    assert all(row["selected_steps"] == 0 for row in models)
    bad = deepcopy(trials); bad[0]["checkpoint"] = {"path": "/other"}
    with pytest.raises(ValueError, match="fallback"):
        runner.model_inventory(bad, parents)


def test_all_source_panels_include_exposed_real_and_authored_denominators():
    assert sum(runner.SINGLE_COUNTS.values()) == 1334
    assert runner.SINGLE_COUNTS["real_exposed"] == 86 and runner.SINGLE_COUNTS["fresh"] == 144
    assert sum(runner.DOCUMENT_COUNTS.values()) == 384

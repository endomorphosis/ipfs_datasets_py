"""Retention gates, matched controls and diagnostic exclusion for the new study."""
from copy import deepcopy

import pytest

from scripts.ops.legal_ir import run_legal_facet_retention_experiment as runner


def metrics(steps=400, new=100):
    value = {k: (0 if 'unsupported' in k else maximum // 2) for k, maximum in runner.metric_keys().items()}
    return value | {'steps': steps, 'tuning_new_exact': new, 'training_new_exact': 0}


@pytest.mark.parametrize('key', ['tuning_earlier_exact','tuning_temporal_exact','tuning_prior_consistency_exact',
    'tuning_document_parent_exact','tuning_document_expanded_exact'])
def test_all_old_gates_allow_only_one_case_loss(key):
    parent, early, late = metrics(new=50), metrics(), metrics(800, 150)
    late[key] = parent[key] - 2
    assert runner.select_stage([early, late], parent) is early
    late[key] = parent[key] - 1
    assert runner.select_stage([early, late], parent) is late


@pytest.mark.parametrize('key', ['tuning_prior_role_exact','tuning_new_exact',
    'tuning_new_document_parent_exact','tuning_new_document_expanded_exact'])
def test_role_new_clause_and_new_document_gates_cannot_regress(key):
    parent, early, late = metrics(), metrics(), metrics(800, 150)
    early[key] = late[key] = parent[key] - 1
    assert runner.select_stage([early, late], parent) is None


@pytest.mark.parametrize('panel', ['document', 'new_document'])
@pytest.mark.parametrize('policy', ['parent', 'expanded'])
def test_every_document_guard_is_required(panel, policy):
    parent, early, late = metrics(), metrics(), metrics(800, 150)
    early[f'tuning_{panel}_{policy}_unsupported_accepted'] = 1
    late[f'tuning_{panel}_{policy}_unsupported_accepted'] = 1
    assert runner.select_stage([early, late], parent) is None


def test_role_normalization_rank_and_training_diagnostic_exclusion():
    parent, early, late = metrics(), metrics(), metrics(800)
    late['training_new_exact'] = 768
    assert runner.select_stage([late, early], parent) is early
    late['tuning_new_exact'] += 1
    assert runner.select_stage([late, early], parent) is late
    early['tuning_prior_role_exact'] += 1
    assert runner.select_stage([late, early], parent) is early
    late['tuning_new_exact'] += 1
    late['tuning_new_document_expanded_exact'] += 1
    assert runner.select_stage([late, early], parent) is late


@pytest.mark.parametrize('change', ['missing','bool','overflow','wrong_steps'])
def test_malformed_stage_metrics_cannot_select(change):
    parent, stages = metrics(), [metrics(), metrics(800)]
    if change == 'missing': stages[0].pop('tuning_prior_role_exact')
    elif change == 'bool': stages[0]['tuning_new_exact'] = True
    elif change == 'overflow': stages[0]['tuning_new_exact'] = 193
    else: stages[0]['steps'] = 200
    with pytest.raises((ValueError, KeyError)): runner.select_stage(stages, parent)


def inventory():
    parents, trials = {}, []
    for architecture in runner.ARCHITECTURES:
        for seed in runner.SEEDS:
            checkpoint = {'path': f'/{architecture}-{seed}', 'sha256': str(seed)}
            parents[(architecture, seed)] = {'checkpoint': checkpoint}
            for objective in runner.OBJECTIVES:
                trials.append({'name': f'{objective}_{architecture}-{seed}', 'arm': f'{objective}_{architecture}',
                    'objective': objective, 'architecture': architecture, 'seed': seed,
                    'enabled': architecture == 'grounding', 'parent': checkpoint, 'checkpoint': checkpoint,
                    'decoder_kind': 'consistency', 'executed_steps': 800, 'selected_steps': 0,
                    'selection': 'parent_fallback_no_acceptable_replacement'})
    return parents, trials


def test_complete_matched_controls_and_fallback_slots():
    parents, trials = inventory(); models, pipelines = runner.model_inventory(trials, parents)
    assert len(models) == 18 and len(pipelines) == len({p['name'] for p in pipelines}) == 36
    assert all(m['selected_steps'] == 0 for m in models)
    bad = deepcopy(trials); bad[0]['checkpoint'] = {'path': '/different'}
    with pytest.raises(ValueError, match='fallback'): runner.model_inventory(bad, parents)


def test_all_updates_and_matched_objective_batches_required(monkeypatch):
    _, trials = inventory()
    for trial in trials:
        trial['stages'] = [{'training_report': [dict(optimizer_step=i, sample=i % 5) for i in range(1, 401)]},
            {'training_report': [dict(optimizer_step=i, sample=i % 5) for i in range(401, 801)]}]
    monkeypatch.setattr(runner, 'read_ref', lambda value: {'batch_exposures': value})
    assert len(runner.audit_trials(trials)) == 12
    trials[0]['stages'][0]['training_report'][0]['sample'] = 999
    with pytest.raises(ValueError, match='matched objectives'): runner.audit_trials(trials)


def test_panel_counts_and_training_diagnostic_not_selected_input_panel():
    assert sum(runner.SINGLE_COUNTS.values()) == 1718 and runner.SINGLE_COUNTS['fresh'] == 192
    assert runner.SINGLE_COUNTS['real_exposed'] == 86 and 'training_new' not in runner.SINGLE_COUNTS
    assert sum(runner.DOCUMENT_COUNTS.values()) == 576

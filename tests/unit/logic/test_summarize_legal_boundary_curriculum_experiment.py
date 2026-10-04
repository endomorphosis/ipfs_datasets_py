from copy import deepcopy
import pytest
from scripts.ops.legal_ir import summarize_legal_boundary_curriculum_experiment as subject


def stages():
    return [{'steps': step, 'old_exact': 35, 'old_decision_exact': 47, 'new_exact': 50, 'new_guard_accept': 0} for step in (200, 400, 600)]


def test_tuning_gate_rejects_document_regression_and_guard_acceptance():
    rows = stages(); rows[0]['old_exact'] = 34; rows[1]['new_guard_accept'] = 1
    assert subject.selection_choice(rows, 36)['steps'] == 600
    rows[2]['old_exact'] = 34
    assert subject.selection_choice(rows, 36) is None


def test_tuning_gate_ranks_new_then_old_then_earliest():
    rows = stages()
    assert subject.selection_choice(rows, 36)['steps'] == 200
    rows[1]['old_decision_exact'] = 48
    assert subject.selection_choice(rows, 36)['steps'] == 400
    rows[2]['new_exact'] = 51
    assert subject.selection_choice(rows, 36)['steps'] == 600


@pytest.mark.parametrize('mutation', ['fresh_score', 'bool', 'bounds', 'step', 'missing'])
def test_tuning_gate_rejects_test_metrics_or_invalid_counts(mutation):
    rows = stages()
    if mutation == 'fresh_score': rows[0]['fresh_exact'] = 72
    elif mutation == 'bool': rows[0]['old_exact'] = True
    elif mutation == 'bounds': rows[0]['new_guard_accept'] = 25
    elif mutation == 'step': rows[0]['steps'] = 400
    else: rows.pop()
    with pytest.raises(ValueError): subject.selection_choice(rows, 36)


def inventory():
    heads = [{'name': 'parent', 'checkpoint': {'sha256': 'old'}}]
    heads += [{'name': f'{p}-{s}', 'checkpoint': {'sha256': f'{p}{s}'}} for p in subject.CURRICULA for s in subject.SEEDS]
    by_name = {h['name']: h for h in heads}
    models = []
    for p in subject.POLICIES:
        for a in subject.ARCHITECTURES:
            for s in subject.SEEDS:
                head = 'parent' if p == 'parent' else f'{p}-{s}'
                models.append({'name': f'{p}_{a}-{s}', 'boundary_policy': p, 'architecture': a, 'seed': s,
                    'boundary_head': head, 'boundary_checkpoint': by_name[head]['checkpoint'],
                    'enabled': a == 'grounding', 'decoder_kind': 'mixed'})
    return models, heads, {m['name']: dict.fromkeys(subject.COUNTS) for m in models}, {h['name']: dict.fromkeys(subject.COUNTS) for h in heads}


def test_inventory_preserves_all_eighteen_slots_even_for_parent_fallback():
    args = inventory()
    for h in args[1]: h['checkpoint'] = args[1][0]['checkpoint']
    for m in args[0]: m['boundary_checkpoint'] = args[1][0]['checkpoint']
    assert subject.verify_inventory(*args) == {'pipeline_slots': 18, 'boundary_heads': 7,
        'selected_pipeline_source_rows': 7776, 'selected_boundary_source_rows': 3024}


@pytest.mark.parametrize('mutation', ['model', 'head', 'panel', 'swapped_seed', 'grounding', 'boundary_ref'])
def test_inventory_rejects_incomplete_or_cross_seed_bindings(mutation):
    models, heads, files, boundaries = inventory()
    if mutation == 'model': models.pop()
    elif mutation == 'head': heads.pop()
    elif mutation == 'panel': files[models[0]['name']].pop('fresh_documents')
    elif mutation == 'swapped_seed': models[-1]['boundary_head'] = 'expanded-1729'
    elif mutation == 'grounding': models[-1]['enabled'] = False
    else: models[-1]['boundary_checkpoint'] = {'sha256': 'foreign'}
    with pytest.raises(ValueError): subject.verify_inventory(models, heads, files, boundaries)


def funnel_fixture():
    sources, targets, predictions, boundaries = [], [], [], []
    for i in range(6):
        identity = str(i); supported = i != 5
        source = {'candidate_id': identity, 'source_sha256': identity}
        target = {**source, 'supported': supported, 'construction': 'test',
            'clauses': [{'rule': {'actor': 'A'}, 'char_start': 0, 'char_end': 5}] if supported else []}
        composition = None if i < 2 else {'source_rule_list': [{'actor': 'A'}],
            'source_plan': {'clauses': [{'char_start': 0, 'char_end': 5 if i != 5 else 4}]}}
        prediction = {**source, 'segmentation_status': 'abstained' if i == 0 else 'segmented',
            'status': 'abstained' if composition is None else 'composed', 'reason': 'test', 'composition': composition}
        bound = {'id': identity, 'source_sha256': identity, 'status': prediction['segmentation_status'],
            'delivered_intervals': None if i == 0 else [[0, 5 if i != 5 else 4]],
            'raw_interval_exact': supported and i != 0, 'delivered_interval_exact': supported and i != 0}
        sources.append(source); targets.append(target); predictions.append(prediction); boundaries.append(bound)
    selection = {'rows': [{'candidate': {'candidate_id': str(i)}} for i in (3, 4, 5)],
        'excluded': [{'candidate_id': str(i)} for i in (0, 1, 2)]}
    batches = [{'candidate_ids': ['3'], 'build_passed': False, 'backend_executed': True},
        {'candidate_ids': ['4', '5'], 'build_passed': True, 'backend_executed': True}]
    return {'rows': predictions}, {'rows': boundaries}, sources, targets, selection, batches


def test_funnel_distinguishes_all_failure_stages_and_false_scope_acceptance():
    result = subject.pipeline_funnel(*funnel_fixture())
    assert result['terminal_stages'] == {'boundary_abstained': 1, 'clause_decode_or_composition_abstained': 1,
        'lowering_unsupported': 1, 'native_build_failed': 1, 'built_joint_exact': 1, 'built_reference_mismatch': 1}
    assert result['metrics']['unsupported_accepted'] == 1
    assert result['builds']['built'] == 2 and result['builds']['built_exact'] == 1
    assert result['builds']['built_reference_mismatch'] == 1


def test_funnel_compiles_matching_rules_with_wrong_occurrences_as_mismatch():
    args = list(funnel_fixture())
    args[0]['rows'][4]['composition']['source_plan']['clauses'][0]['char_end'] = 4
    args[1]['rows'][4]['delivered_intervals'] = [[0, 4]]
    args[1]['rows'][4]['delivered_interval_exact'] = False
    result = subject.pipeline_funnel(*args)
    assert result['builds']['built_exact'] == 0
    assert result['builds']['built_canonical_only_exact'] == 1
    assert result['builds']['built_reference_mismatch'] == 2


@pytest.mark.parametrize('mutation', ['duplicate_selection', 'missing_excluded', 'missing_batch', 'wrong_boundary'])
def test_funnel_rejects_dropped_cases_or_switched_plan(mutation):
    args = list(funnel_fixture())
    if mutation == 'duplicate_selection': args[4]['rows'][1] = args[4]['rows'][0]
    elif mutation == 'missing_excluded': args[4]['excluded'].pop()
    elif mutation == 'missing_batch': args[5].pop()
    else: args[1]['rows'][4]['delivered_intervals'] = [[0, 3]]
    with pytest.raises(ValueError): subject.pipeline_funnel(*args)


def training_fixture(monkeypatch):
    replay = [{'candidate_id': 'old-' + str(i)} for i in range(192)]
    added = [{'candidate_id': 'new-' + str(i)} for i in range(384)]
    tune = {'old': [{'candidate_id': 'ot'}], 'new': [{'candidate_id': 'nt'}]}
    parent_ref = {'path': 'parent', 'sha256': 'parent-hash'}
    parent = {'optimizer_steps': 200, 'model_state': {'a': [1.]}}
    manifest = {'curriculum': 'expanded', 'original_replay_sha256': subject.digest(replay),
        'new_train_sha256': subject.digest(added), 'old_quota': 6, 'new_quota': 6, 'sampler_seed': 1729,
        'batch_size': 12, 'additional_optimizer_updates': 600,
        'sampler': 'shared_random.Random(seed); lazy_shuffle_range_at_pool_exhaustion; exact_quota_wraparound; old_then_new; no_batch_shuffle'}
    tuning = {k: subject.digest(v) for k, v in tune.items()}
    stage_rows, checkpoints = [], {}
    for steps in (200, 400, 600):
        reference = {'path': str(steps)}
        checkpoints[str(steps)] = {'optimizer_steps': 200 + steps, 'model_state': {'a': [2.]},
            'training_manifest_sha256': subject.digest(manifest), 'tuning_manifest_sha256': subject.digest(tuning)}
        stage_rows.append({'steps': steps, 'cumulative_optimizer_steps': 200 + steps, 'checkpoint': reference})
    batches = subject.independent_schedule(replay, added, 'expanded', 1729)
    record = {'curriculum': 'expanded', 'seed': 1729, 'name': 'expanded-1729', 'initial': parent_ref,
        'initial_model_state_sha256': subject.digest(parent['model_state']), 'shared_pretrained_initialization': True,
        'seed_controls_minibatch_order_only': True, 'independent_model_initializations': False,
        'training_manifest': manifest, 'training_manifest_sha256': subject.digest(manifest),
        'tuning_manifest': tuning, 'tuning_manifest_sha256': subject.digest(tuning),
        'executed_optimizer_updates': 600, 'losses': [1.] * 600, 'batches': batches,
        'inherited_optimizer_steps': 200, 'final_cumulative_optimizer_steps': 800,
        'optimizer_reset': True, 'optimizer_resumption_supported': False, 'torch_threads': 1,
        'fresh_targets_opened': False, 'regression_targets_opened': False,
        'training_step_seconds': [.1] * 600, 'maximum_total_trial_seconds': 600,
        'optimizer_training_seconds': 60., 'elapsed_seconds_including_stage_tuning': 70.,
        'batch_schedule_sha256': subject.digest(batches), 'stages': stage_rows, 'changed_parameter_names': ['a']}
    monkeypatch.setattr(subject, 'read_ref', lambda ref: deepcopy(checkpoints[ref['path']]))
    monkeypatch.setattr(subject.boundary, 'restore', lambda cp: None)
    return record, parent_ref, parent, replay, added, tune, checkpoints


def test_training_contract_reconstructs_every_batch_and_cumulative_step(monkeypatch):
    args = training_fixture(monkeypatch)
    report = subject.verify_training_contract(*args[:-1])
    assert report['executed_optimizer_updates'] == 600
    assert report['independent_batch_rows_verified'] == 7200
    assert [r['cumulative_optimizer_steps'] for r in report['stages']] == [400, 600, 800]
    assert report['optimizer_trajectory_replayed'] is False


@pytest.mark.parametrize('mutation', ['parent', 'manifest', 'quota', 'batch_order', 'fresh_fit', 'missing_update',
    'nonfinite_loss', 'optimizer_resume', 'wallclock', 'cumulative_steps', 'checkpoint_manifest', 'unchanged_weights'])
def test_training_contract_rejects_corrupt_initialization_fitting_or_update_receipts(monkeypatch, mutation):
    args = training_fixture(monkeypatch); record, parent_ref, parent, replay, added, tune, cps = args
    if mutation == 'parent': record['initial_model_state_sha256'] = 'foreign'
    elif mutation == 'manifest': record['training_manifest']['new_train_sha256'] = 'foreign'
    elif mutation == 'quota': record['training_manifest']['new_quota'] = 7
    elif mutation == 'batch_order': record['batches'][0]['old_ids'].reverse(); record['batch_schedule_sha256'] = subject.digest(record['batches'])
    elif mutation == 'fresh_fit': record['batches'][0]['new_ids'][0] = 'fresh-case'; record['batch_schedule_sha256'] = subject.digest(record['batches'])
    elif mutation == 'missing_update': record['losses'].pop()
    elif mutation == 'nonfinite_loss': record['losses'][0] = float('nan')
    elif mutation == 'optimizer_resume': record['optimizer_resumption_supported'] = True
    elif mutation == 'wallclock': record['elapsed_seconds_including_stage_tuning'] = 601.
    elif mutation == 'cumulative_steps': cps['200']['optimizer_steps'] = 200
    elif mutation == 'checkpoint_manifest': cps['200']['training_manifest_sha256'] = 'foreign'
    else: cps['200']['model_state']['a'] = [1.]
    with pytest.raises(ValueError): subject.verify_training_contract(*args[:-1])


def test_independent_batch_schedule_matches_declared_cycling_including_wraparound():
    from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as runner
    replay = [{'candidate_id': 'old-' + str(i)} for i in range(19)]
    added = [{'candidate_id': 'new-' + str(i)} for i in range(41)]
    for curriculum in subject.CURRICULA:
        for seed in subject.SEEDS:
            expected = [record for _, record in runner.batch_schedule(replay, added, curriculum, seed)]
            assert subject.independent_schedule(replay, added, curriculum, seed) == expected


def boundary_fixture(abstain=False):
    source_text = 'Office must retain files.'
    source = {'candidate_id': 'a', 'source_text': source_text, 'source_sha256': subject.boundary.text_sha(source_text)}
    target = {**source, 'supported': True, 'clauses': [{'char_start': 0, 'char_end': len(source_text), 'rule': {'actor': 'Office'}}],
        'construction': 'plain', 'repeated_rule_occurrences': False}
    tokens = subject.boundary.tokenize(source_text); ends = [len(tokens)-1]
    plan = None if abstain else subject.boundary.source_plan(source, tokens, ends)
    prediction = {'candidate_id': 'a', 'source_sha256': source['source_sha256'],
        'status': 'abstained' if abstain else 'segmented', 'target_access': False,
        'boundary_token_indices': ends, 'predicted_rule_count': 1,
        'boundary_logits': [-1.] * (len(tokens)-1) + [1.], 'plan': plan,
        'raw_learned_scope_supported': not abstain, 'reason': 'learned_scope_abstention' if abstain else None}
    return {'rows': [prediction]}, [source], [target]


def test_raw_exact_boundaries_remain_visible_when_scope_policy_abstains():
    result = subject.score_boundaries(*boundary_fixture(abstain=True))
    assert result['supported_raw_interval_exact'] == result['supported_raw_exact_but_abstained'] == 1
    assert result['supported_delivered_interval_exact'] == 0
    accepted = subject.score_boundaries(*boundary_fixture())
    assert accepted['supported_delivered_interval_exact'] == 1


@pytest.mark.parametrize('mutation', ['threshold', 'identity', 'duplicate', 'source_hash'])
def test_boundary_contract_rejects_corrupt_logits_or_source_joins(mutation):
    generation, sources, targets = boundary_fixture()
    if mutation == 'threshold': generation['rows'][0]['boundary_logits'][0] = 1.
    elif mutation == 'identity': generation['rows'][0]['candidate_id'] = 'other'
    elif mutation == 'duplicate': generation['rows'].append(generation['rows'][0])
    else: targets[0]['source_sha256'] = 'foreign'
    with pytest.raises(ValueError): subject.score_boundaries(generation, sources, targets)

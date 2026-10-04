"""Structured learned decoding contracts; authored vectors are not GTE evidence."""
from copy import deepcopy
import hashlib

import pytest

torch = pytest.importorskip('torch')
np = pytest.importorskip('numpy')
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal


def target(domain, first, second=0):
    if domain == 'intent_ir':
        return dict(kind='intent_rich_ast', document=dict(kind='atom', actor=['operator', 'auditor'][first],
            action=['save', 'erase'][second], object='report', modality='required'))
    if domain == 'ui_ux_ir':
        return dict(kind='ui_component', document=dict(component_id=['submit', 'cancel'][first], role=['button', 'input'][second]))
    if domain == 'security_ir':
        from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
        return dict(kind='program_expression', document=ProgramExpression(['expr:one', 'expr:two'][first], 'literal', 'integer',
            source_ref_ids=('authored-source',), attributes={'value': second}).to_dict())
    return dict(rules=[dict(modality='O', actor=['agency', 'auditor'][first], action=['save', 'erase'][second], object='report',
        conditions=[], exceptions=[], temporal=[])])


@pytest.fixture(scope='module')
def parent():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain='legal_ir', lineage_id='current_legal_v2', dimension=384,
            runtime_profile='unit-test-structured-source/v1', core_sha256='a'*64)
        rows = [dict(id='parent-training', source_text='The agency must save the report.',
            latent=[.5]+[0.]*383, embedding=[.3]+[0.]*383, canonical_ir=target('legal_ir', 0))]
        checkpoint = legal.build_checkpoint(binding, rows, [], hidden_size=16, token_embedding_dim=8,
            projection_width=4, batch_size=1)
        return legal.train(checkpoint, rows, [], epochs=1, max_seconds=30)['checkpoint']
    finally:
        torch.set_num_threads(previous)


def rows(domain, split, pairs=((0, 0), (0, 1), (1, 0))):
    result = []
    for index, (first, second) in enumerate(pairs):
        for variant in range(2):
            embedding = [float(first)*2-1, float(second)*2-1,
                (.001 if split == 'train' else .011) + variant*.001 + index*.0001]+[0.]*381
            result.append(dict(id=f'{split}-{index}-{variant}', source_text=f'{split} authored {index} variant {variant}',
                embedding=embedding, target=target(domain, first, second)))
    return result


@pytest.fixture(scope='module', params=subject.DOMAINS)
def trained(request, parent):
    original = deepcopy(parent)
    result = subject.train(request.param, rows(request.param, 'train'), rows(request.param, 'tuning'), parent_projection=parent)
    assert parent == original
    return result['checkpoint']


def inputs(data):
    return [{key: row[key] for key in ('id', 'source_text', 'embedding')} for row in data]


def test_fitted_classifier_reconstructs_tuning_and_novel_combinations(trained):
    domain = trained['domain_id']
    assert subject.evaluate(trained, rows(domain, 'tuning'))['exact_targets'] == 6
    novel = rows(domain, 'novel', pairs=((1, 1),))
    assert all(row['target'] not in [item['target'] for item in rows(domain, 'train')] for row in novel)
    report = subject.evaluate(trained, novel)
    assert report['exact_targets'] == 2
    assert report['semantic_leaf_accuracy'] == 1.
    assert all(row['target_access'] is False and row['teacher_forcing'] is False for row in report['rows'])


def test_actual_encoder_and_head_parameters_are_consumed(trained):
    runtime = subject.Runtime(trained)
    data = rows(trained['domain_id'], 'tuning')
    baseline = runtime.infer(inputs(data))
    changed = deepcopy(trained)
    changed['projection_state']['projection_up.bias'][0] += .25
    changed['projection_sha256'] = subject.digest(changed['projection_state'])
    after = subject.Runtime(changed).infer(inputs(data))
    for before, actual in zip(baseline['rows'], after['rows']):
        assert actual['projected_embedding'][0] == pytest.approx(before['projected_embedding'][0] + .25)
    zero = subject.evaluate(trained, data, weight_ablation='zero_head')
    assert zero['exact_targets'] < len(data)
    shuffled = subject.evaluate(trained, data, weight_ablation='shuffle_embeddings')
    assert shuffled['exact_targets'] < len(data)
    residual_zero = runtime.infer(inputs(data), weight_ablation='zero_projection')
    assert residual_zero['rows'][0]['projected_embedding'] == data[0]['embedding']
    assert runtime.infer(inputs(data)) == baseline


def test_inference_has_no_target_or_source_parser_access(trained):
    runtime = subject.Runtime(trained)
    data = rows(trained['domain_id'], 'tuning')[:1]
    with pytest.raises(ValueError, match='closed domain row'):
        runtime.infer(data)
    baseline = runtime.infer(inputs(data))['rows'][0]
    data[0]['source_text'] = 'Different provenance with identical numerical input.'
    after = runtime.infer(inputs(data))['rows'][0]
    for key in ('candidate_ir', 'projected_embedding', 'predicted_classes'):
        assert baseline[key] == after[key]
    assert baseline['source_sha256'] != after['source_sha256']
    with pytest.raises(ValueError, match='at least two'):
        runtime.infer(inputs(data), weight_ablation='shuffle_embeddings')


def test_reload_and_bound_domain_integrity(trained, tmp_path):
    raw = subject._raw(trained)
    path = tmp_path/'checkpoint.json'; path.write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    runtime = subject.load_checkpoint(path, expected_sha256=checksum, expected_domain=trained['domain_id'])
    assert runtime.describe()['dimension'] == 384
    assert runtime.describe()['whole_target_retrieval'] is False
    with pytest.raises(ValueError, match='another domain'):
        subject.load_checkpoint(path, expected_sha256=checksum, expected_domain='other')
    with pytest.raises(ValueError, match='bytes differ'):
        subject.load_checkpoint(path, expected_sha256='0'*64, expected_domain=trained['domain_id'])
    changed = deepcopy(trained); changed['head_state']['bias'][0] += 1.
    with pytest.raises(ValueError, match='head digest'):
        subject.Runtime(changed)
    changed = deepcopy(trained); changed['projection_state']['projection_up.bias'][0] += .1
    with pytest.raises(ValueError, match='projection digest'):
        subject.Runtime(changed)
    changed = deepcopy(trained); changed['implementation']['runtime_sha256'] = '0'*64
    with pytest.raises(ValueError, match='implementation pins'):
        subject.Runtime(changed)


def test_training_provenance_and_no_whole_targets_stored(trained, parent):
    assert trained['projection_state'] == {key: parent['model_state'][key] for key in subject.PROJECTION_KEYS}
    assert trained['lineage']['parent_encoder_frozen'] is True
    assert trained['lineage']['random_parameters_used'] is False
    assert trained['training']['test_used_for_selection'] is False
    assert trained['training']['factorizations'] == 4
    assert trained['training']['optimizer_steps'] == 0
    assert trained['training']['fit_unique_examples_per_second'] > 0
    assert trained['target_schema']['whole_target_memory'] is False
    assert 'target' not in trained['training_manifest'][0]
    for slot in trained['target_schema']['slots']:
        value = trained['target_schema']['template']
        for part in slot['path']:
            value = value[part]
        assert value is None


def test_tuning_unknown_class_or_consensus_change_is_rejected(parent):
    training, tuning = rows('legal_ir', 'train'), rows('legal_ir', 'tuning')
    tuning[0]['target']['rules'][0]['actor'] = 'unknown-actor'
    with pytest.raises(ValueError, match='outside training vocabulary'):
        subject.train('legal_ir', training, tuning, parent_projection=parent)
    tuning = rows('legal_ir', 'tuning')
    tuning[0]['target']['rules'][0]['object'] = 'different-object'
    with pytest.raises(ValueError, match='consensus constants'):
        subject.train('legal_ir', training, tuning, parent_projection=parent)


@pytest.mark.parametrize('change', ('array_length', 'missing_key', 'scalar_type'))
def test_variable_schema_is_explicitly_rejected(change):
    one = {'values': [1], 'constant': 'x'}
    two = deepcopy(one)
    if change == 'array_length':
        two['values'].append(2)
    elif change == 'missing_key':
        del two['constant']
    else:
        two['values'][0] = True
    with pytest.raises(ValueError, match='fixed typed JSON tree'):
        subject._fit_schema([{'target': one}, {'target': two}])


def test_split_overlap_rejected(parent):
    data = rows('legal_ir', 'train')
    with pytest.raises(ValueError, match='overlap'):
        subject.train('legal_ir', data, data, parent_projection=parent)


def test_bad_ridge_config_rejected(parent):
    for grid in ([], [0.], [float('nan')], [.1, .01], [.1, .1]):
        with pytest.raises(ValueError, match='ridge grid'):
            subject.train('legal_ir', rows('legal_ir', 'train'), rows('legal_ir', 'tuning'),
                parent_projection=parent, config={'ridges': grid})


def test_projection_matches_inherited_legal_torch_encoder(parent):
    state = subject._projection(parent)
    data = rows('legal_ir', 'train')
    with subject.native._cpu() as reserved:
        model = legal._model(parent['binding'], parent['codec'], parent['config'])
        model.load_state_dict({name: reserved.tensor(value) for name, value in parent['model_state'].items()})
        expected = model.project(reserved.tensor([row['embedding'] for row in data])).detach().numpy()
    observed = subject._project(np, data, state)
    assert np.allclose(expected, observed, atol=1e-6)


def test_slot_models_are_algebraically_equivalent_to_independent_ridge_fits(trained):
    data = rows(trained['domain_id'], 'train')
    x, _ = subject._normalize(np, subject._project(np, data, trained['projection_state']), trained['input_transform'])
    y, _ = subject._targets(np, data, trained['target_schema'])
    expected = np.asarray(trained['head_state']['weights'])
    ridge = trained['training']['selected_ridge']
    for column in range(y.shape[1]):
        dual = np.linalg.solve(x@x.T + ridge*np.eye(len(data)), y[:, column]-y[:, column].mean())
        assert np.allclose(expected[:, column], x.T@dual, atol=1e-10)


def test_evaluation_counts_unsupported_gold_in_denominator(trained):
    if trained['domain_id'] != 'legal_ir':
        return
    rows = [dict(id='unseen-test', source_text='An unseen actor must save the report.',
        embedding=[.91]+[0.]*383, target=target('legal_ir', 0))]
    rows[0]['target']['rules'][0]['actor'] = 'unseen-actor'
    result = subject.evaluate(trained, rows)
    assert result['count'] == 1
    assert result['exact_targets'] == 0
    assert result['outside_training_coverage'] == 1
    assert result['rows'][0]['within_training_coverage'] is False


def test_runtime_rejects_negative_array_slot_alias(trained):
    if trained['domain_id'] != 'legal_ir':
        return
    changed = deepcopy(trained)
    path = changed['target_schema']['slots'][0]['path']
    assert path[0] == 'rules' and path[1] == 0
    path[1] = -1
    with pytest.raises(ValueError, match='noncanonical scalar path'):
        subject.Runtime(changed)

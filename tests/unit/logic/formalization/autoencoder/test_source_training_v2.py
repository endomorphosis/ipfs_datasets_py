"""Bounded numerical tests; synthetic vectors are explicitly not corpus evidence."""
from copy import deepcopy
import hashlib
import json

import pytest

torch = pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal


@pytest.fixture(scope='module')
def parent():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = dict(domain='legal_ir', lineage_id='current_legal_v2', dimension=384,
            runtime_profile='unit-test-source-v2/v1', core_sha256='a' * 64)
        rows = [dict(id='parent-training', source_text='The agency must save the report.',
            latent=[.5]+[0.]*383, embedding=[.3]+[0.]*383, canonical_ir=target('legal_ir', 0))]
        state = legal.build_checkpoint(binding, rows, [], hidden_size=16, token_embedding_dim=8,
            projection_width=4, batch_size=1)
        return legal.train(state, rows, [], epochs=1, max_seconds=30)['checkpoint']
    finally:
        torch.set_num_threads(previous)


def target(domain, variant):
    if domain == 'intent_ir':
        return dict(kind='intent_rich_ast', document=dict(kind='atom', actor=['operator', 'auditor'][variant],
            action='save', object='report', modality='required'))
    if domain == 'ui_ux_ir':
        return dict(kind='ui_component', document=dict(component_id='submit', role=['button', 'input'][variant]))
    if domain == 'security_ir':
        from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
        return dict(kind='program_expression', document=ProgramExpression('expr:one', 'literal', 'integer',
            source_ref_ids=('authored-source',), attributes={'value': variant}).to_dict())
    return dict(rules=[dict(modality='O', actor=['agency', 'auditor'][variant], action='save', object='report',
        conditions=[], exceptions=[], temporal=[])])


def rows(domain, split):
    return [dict(id=f'{split}-{index}', source_text=f'{split} authored {index} source',
        embedding=[(.2 if split == 'train' else .21) + index * .1]+[0.]*383,
        target=target(domain, index % 2)) for index in range(4 if split == 'train' else 2)]


@pytest.fixture(scope='module', params=subject.DOMAINS)
def trained(request, parent):
    before = deepcopy(parent)
    result = subject.train(request.param, rows(request.param, 'train'), rows(request.param, 'tuning'),
        parent_projection=parent, config=dict(epochs=3, batch_size=2, max_seconds=30,
            validation_interval=1, patience=0, max_optimizer_steps=6, max_target_tokens=192))
    assert parent == before
    return result['checkpoint']


def test_legal_validation_does_not_coerce_or_drop_fields():
    document = target('legal_ir', 0)
    assert subject.validate_target('legal_ir', document)['canonical_ir'] == document
    document['rules'][0]['extra'] = True
    with pytest.raises(ValueError):
        subject.validate_target('legal_ir', document)


def test_json_record_paths_and_weights_are_train_derived():
    document = {'x': 'x', 'z': [True, 1, None]}
    records = subject._token_records(document)
    assert ''.join(token for token, _, _ in records) == subject._raw(document).decode()
    assert [path for token, role, path in records if role == 'leaf' and token == '"x"'] == [('x',)]
    assert [path for token, role, path in records if role == 'key' and token == '"x"'] == [()]
    paths = subject._varying_paths([{'target': {'x': True}}, {'target': {'x': 1}}])
    assert paths == [['x']]


def test_semantic_selection_prioritizes_actual_generation():
    common = dict(exact_targets=0, semantic_leaf_accuracy=.5, objective=.1)
    assert subject._selection({**common, 'exact_targets': 1, 'objective': 10.}, 'semantic_v2') > subject._selection(common, 'semantic_v2')
    assert subject._selection({**common, 'objective': 10.}, 'reference_ce') < subject._selection(common, 'reference_ce')


def test_weighting_changes_leaf_loss_without_validation_vocabulary(parent):
    config = subject._config(dict(strategy='semantic_v2'), parent['config'])
    data = rows('intent_ir', 'train')
    paths = subject._varying_paths(data)
    vocab = [*subject.native.SPECIAL, *sorted({token for row in data for token, _, _ in subject._token_records(row['target'])})]
    transform = subject._transform(torch, data, 'none')
    _, labels, weights = subject._encoded(torch, data, vocab, paths, config, transform)
    assert float(weights.max()) == 4.
    assert float(weights[labels == vocab.index('"actor"')][0]) == .25
    assert float(weights[labels == vocab.index('"operator"')][0]) == 4.
    changed = deepcopy(data[:1]); changed[0]['target']['document']['actor'] = 'unseen-person'
    with pytest.raises(ValueError, match='outside training vocabulary'):
        subject._encoded(torch, changed, vocab, paths, config, transform)


def test_training_budget_selection_and_real_weight_consumption(trained):
    metrics = trained['training']
    assert metrics['optimizer_steps'] == 6
    assert metrics['stopped_reason'] == 'optimizer_step_budget'
    assert metrics['test_used_for_selection'] is False
    assert metrics['selected_validation']['free_running_metrics_teacher_forced'] is False
    assert metrics['selected_validation']['teacher_forcing_selection_role'] == 'tertiary_tiebreaker'
    assert metrics['optimizer_tokens_per_second'] > 0
    assert trained['lineage']['random_parameters_used'] is False
    runtime = subject.Runtime(trained)
    inputs = [{key: row[key] for key in ('id', 'source_text', 'embedding')} for row in rows(trained['domain_id'], 'tuning')]
    previous = torch.get_num_threads()
    baseline = runtime.infer(inputs)
    changed = deepcopy(trained)
    changed['model_state']['projection_up.bias'][0] += .125
    changed['weights_sha256'] = subject.digest(changed['model_state'])
    after = subject.Runtime(changed).infer(inputs)
    scale = trained['input_transform']['scale']
    for a, b in zip(baseline['rows'], after['rows']):
        assert b['reconstructed_embedding'][0] == pytest.approx(a['reconstructed_embedding'][0] + scale * .125, abs=1e-6)
    assert all(row['candidate_ir'] is None for row in runtime.infer(inputs, weight_ablation='zero_decoder')['rows'])
    assert runtime.infer(inputs) == baseline
    assert torch.get_num_threads() == previous


def test_batched_inference_is_target_free_and_embedding_conditioned(trained):
    runtime = subject.Runtime(trained)
    supplied = rows(trained['domain_id'], 'tuning')[0]
    with pytest.raises(ValueError, match='closed domain row'):
        runtime.infer([supplied])
    inputs = {key: supplied[key] for key in ('id', 'source_text', 'embedding')}
    before = runtime.infer([inputs])['rows'][0]
    after = runtime.infer([{**inputs, 'source_text': 'Different provenance only.'}])['rows'][0]
    for key in ('candidate_ir', 'generated_tokens', 'reconstructed_embedding'):
        assert before[key] == after[key]
    assert before['source_sha256'] != after['source_sha256']
    result = subject.evaluate(trained, rows(trained['domain_id'], 'tuning'))
    assert result['count'] == 2
    assert result['semantic_leaf_count'] > 0
    assert all(row['target_access'] is False for row in result['rows'])


def test_reload_integrity_domain_and_pins(trained, tmp_path):
    raw = subject._raw(trained)
    path = tmp_path/'checkpoint.json'; path.write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    assert subject.load_checkpoint(path, expected_sha256=checksum, expected_domain=trained['domain_id']).describe()['dimension'] == 384
    with pytest.raises(ValueError, match='another domain'):
        subject.load_checkpoint(path, expected_sha256=checksum, expected_domain='other')
    changed = deepcopy(trained); changed['implementation']['runtime_sha256'] = '0'*64
    with pytest.raises(ValueError, match='implementation pins'):
        subject.Runtime(changed)
    changed = deepcopy(trained); changed['model_state']['projection_up.bias'][0] += 1
    with pytest.raises(ValueError, match='weight digest'):
        subject.Runtime(changed)


def test_split_overlap_rejected(parent):
    data = rows('legal_ir', 'train')
    with pytest.raises(ValueError, match='overlap'):
        subject.train('legal_ir', data, data, parent_projection=parent)


def test_raw_and_centered_transform_preserve_original_coordinates():
    data = rows('legal_ir', 'train')
    transform = subject._transform(torch, data, 'center_rms')
    vectors = torch.tensor([row['embedding'] for row in data])
    centered = (vectors-torch.tensor(transform['mean']))/transform['scale']
    assert torch.allclose(centered.mean(0), torch.zeros(384), atol=1e-6)
    assert torch.allclose(centered*transform['scale']+torch.tensor(transform['mean']), vectors)
    assert subject._transform(torch, data, 'none')['scale'] == 1.


def test_partial_epoch_is_validated_at_step_budget(parent):
    result = subject.train('legal_ir', rows('legal_ir', 'train'), rows('legal_ir', 'tuning'),
        parent_projection=parent, config=dict(epochs=3, batch_size=1, max_seconds=30,
            validation_interval=3, patience=0, max_optimizer_steps=1, max_target_tokens=192))
    metrics = result['metrics']
    assert metrics['optimizer_steps'] == 1
    assert metrics['stopped_reason'] == 'optimizer_step_budget'
    assert len(metrics['history']) == 1
    assert metrics['history'][0]['epoch_complete'] is False
    assert metrics['history'][0]['optimizer_steps'] == 1


def test_optional_guards_are_semantic_and_absence_is_scored():
    rows = [{'target': {'conditions': []}}, {'target': {'conditions': ['authorized']}}]
    paths = subject._varying_paths(rows)
    assert ['conditions'] in paths
    assert ['conditions', 0] in paths
    absent, present = map(lambda row: subject._leaves(row['target']), rows)
    for path in map(tuple, paths):
        assert not subject._same_leaf(absent.get(path, subject._MISSING), present.get(path, subject._MISSING))
    assert subject._same_leaf(subject._MISSING, subject._MISSING)
    assert not subject._same_leaf(None, subject._MISSING)


def test_exact_evaluation_preserves_scalar_types(trained, monkeypatch):
    domain = trained['domain_id']
    if domain != 'security_ir':
        return
    rows = [dict(id='typed-evaluation', source_text='A Boolean literal.', embedding=[.91]+[0.]*383,
                 target=target(domain, 1))]
    wrong = deepcopy(rows[0]['target'])
    wrong['document']['attributes']['value'] = True
    subject.validate_target(domain, wrong)
    monkeypatch.setattr(subject.Runtime, 'infer', lambda self, inputs: {'rows': [{'candidate_ir': wrong}]})
    report = subject.evaluate(trained, rows)
    assert report['exact_targets'] == 0


def test_equal_length_batches_shuffle_members_each_epoch():
    generator = torch.Generator().manual_seed(1729)
    lengths = torch.tensor([20]*24)
    first = subject._length_buckets(torch, lengths, 4, generator)
    second = subject._length_buckets(torch, lengths, 4, generator)
    assert sorted(torch.cat(first).tolist()) == list(range(24))
    assert sorted(torch.cat(second).tolist()) == list(range(24))
    assert {frozenset(batch.tolist()) for batch in first} != {frozenset(batch.tolist()) for batch in second}

"""Retained native768 record replay with authored, nonexecuted producer fixtures.

No embeddings, weights, tokenizer, numerical backend or native operation runs.
Fixtures reproduce recorded data contracts; passing them grants no native or
semantic authority.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_native768_contexts as subject


def _save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _load(reference):
    return json.loads(Path(reference['path']).read_bytes())


@pytest.fixture
def retained(tmp_path, monkeypatch):
    producer = subject._producer_metadata()
    profile = producer.reference._PROFILE

    def forbidden(*args, **kwargs):
        raise AssertionError('retained inspection invoked a numerical/weight owner')

    for owner, names in ((producer, ('embed_rows', '_load_backend', '_verify_dense_path')),
                         (producer.reference, ('embed_rows', '_load_backend', '_vectors', '_tokenize')),
                         (profile, ('inspect_local_assets',))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)

    sources = {}
    for split, actor in zip(subject.SPLITS, ('agency', 'board', 'clerk', 'auditor')):
        text = 'The ' + actor + ' shall disclose records.'
        sources[split] = [{'id': split, 'source_text': text,
            'source_sha256': hashlib.sha256(text.encode()).hexdigest()}]
    source_ref = _save(tmp_path / 'sources.json', sources)
    entries = [{'relative_to': role, 'path': name, **value}
        for (role, name), value in sorted(profile.PUBLISHED_ASSETS.items())]
    asset_manifest = {'schema': profile.MANIFEST_SCHEMA, 'model_revision': profile.MODEL_REV,
        'code_revision': profile.CODE_REV, 'files': entries}
    asset_ref = _save(tmp_path / 'assets.json', asset_manifest)
    roots = {'model_directory': str(tmp_path / 'absent-model-weights'),
        'code_directory': str(tmp_path / 'absent-model-code')}
    receipts = []
    for ordinal, split in enumerate(subject.SPLITS):
        vector = [0.] * 768
        vector[ordinal] = 1.
        receipts.append({'schema': 'gte-multilingual-embedding-receipt/v1',
            'id': 'upstream-' + split, 'source_sha256': sources[split][0]['source_sha256'],
            'profile_id': producer.PROFILE_ID, 'dimension': 768, 'embedding': vector,
            'token_count_including_special_tokens': 5, 'token_input_sha256': str(ordinal + 1) * 64,
            'truncated': False, 'normalized': True, 'asset_manifest_sha256': asset_ref['sha256']})
    report = {'schema': producer.SCHEMA, 'status': 'completed', 'profile_id': producer.PROFILE_ID,
        'input_row_count': 4, 'receipt_count': 4, 'receipts': receipts,
        'assets': {'schema': profile.RECEIPT_SCHEMA, 'status': 'available', 'profile_id': profile.PROFILE_ID,
            'model_revision': profile.MODEL_REV, 'code_revision': profile.CODE_REV,
            'manifest_sha256': asset_ref['sha256'], **roots, 'files': entries,
            'unavailable_reasons': [], 'proof_authority': False, 'model_numerics_verified': False},
        'implementation': producer._implementation(),
        'complete_checkpoint_loading': {'architecture': 'NewForTokenClassification', 'tensor_count': 138,
            'classifier_loaded': True, 'missing_keys': [], 'unexpected_keys': [],
            'mismatched_keys': [], 'error_msgs': []},
        'dense_path_verification': {'encoder_and_complete_hidden_states_bitwise_equal': True},
        'execution_profile': {'batch_size': 1, 'device': 'cpu', 'dtype': 'float32',
            'attention_implementation': 'eager', 'padding_side': 'right', 'pooling': 'cls',
            'normalization': 'l2', 'max_tokens_including_special_tokens': 8192, 'overlength_policy': 'reject'},
        'model_inference_executed': True, 'runtime_compatibility_verified': True,
        'maximum_context_numerics_verified': False, 'training_executed': False,
        'download_executed': False, 'ir_decoder_executed': False,
        'source_semantics_verified': False, 'proof_authority': False}
    report_ref = _save(tmp_path / 'native-record.json', report)
    config = {'schema': 'legal-native768-context-preparation/v1', 'sources': source_ref,
        'asset_manifest': asset_ref, **roots, 'cache_reports': [report_ref], 'resources': {},
        'batch_size': 1, 'pilot_unique_sources': None,
        # The native-only API must never read or replay these sibling lanes.
        'trained384_bundle': None, 'trained384_contexts': None, 'learned8_availability': None}
    config_ref = _save(tmp_path / 'configuration.json', config)
    implementations = [subject.ref(path) for path in
        (producer.__file__, producer.reference.__file__, profile.__file__)]
    producer_sha = subject.digest({item['path']: item['sha256'] for item in implementations})
    contexts = {}
    for split, upstream in zip(subject.SPLITS, receipts):
        row = subject.make_context(sources[split][0], {'receipt': upstream, 'producer_report': report_ref},
            source_artifact=source_ref, producer_sha256=producer_sha, reused=True)
        contexts[split] = _save(tmp_path / ('contexts-' + split + '.json'), [row])
    manifest = {'schema': 'legal-native768-context-manifest/v1', 'completed': True,
        'configuration': config_ref, 'source_artifact': source_ref, 'implementation_files': implementations,
        'producer_reports': [report_ref], 'representations': {'native768': {'dimension': 768,
            'representation_id': producer.PROFILE_ID, 'producer_sha256': producer_sha,
            'contexts': contexts, 'lineage_artifacts': [config_ref, asset_ref, report_ref]},
            'trained384': {'outside_native_only_scope': True}},
        'context_count': 4, 'unique_source_count': 4,
        'selected_source_sha256': sorted(row[0]['source_sha256'] for row in sources.values()),
        'pilot_unique_sources': None, 'target_access': False, 'training_executed': False,
        'source_semantics_verified': False, 'proof_authority': False}
    manifest_ref = _save(tmp_path / 'manifest.json', manifest)
    return {'path': tmp_path, 'manifest': manifest, 'manifest_ref': manifest_ref,
        'sources': sources, 'producer': producer, 'report': report, 'config': config}


def _request(retained, *splits):
    return [{key: retained['sources'][split][0][key] for key in ('id', 'source_text')} for split in splits]


def _repin_manifest(retained):
    retained['manifest_ref'] = _save(retained['path'] / 'manifest.json', retained['manifest'])
    return retained['manifest_ref']


def test_exact_ordered_native_rows_and_recorded_provenance_without_numerical_calls(retained):
    request = _request(retained, 'oov', 'train')
    original = deepcopy(request)
    result = subject.verify_native768_contexts(retained['manifest_ref'], sources=request)
    assert [row['id'] for row in result['contexts']] == ['oov', 'train']
    assert result['contexts'][0]['context'][3] == 1.
    assert result['representation']['dimension'] == 768
    assert result['context_contract']['training_index_sha256'] == retained['manifest_ref']['sha256']
    assert result['provenance']['original_context_count'] == 4
    assert result['provenance']['selected_count'] == 2
    assert [row['splits'] for row in result['provenance']['selected_source_splits']] == [['oov'], ['train']]
    assert result['provenance']['trained384_sibling_checked'] is False
    assert result['provenance']['weights_read'] is False
    assert result['provenance']['execution_attestation'] is False
    assert result['provenance']['raw_token_ids_retained'] is False
    assert all(result[name] is False for name in ('encoder_reexecuted', 'target_access',
        'training_executed', 'source_semantics_verified', 'proof_authority', 'qualified', 'admitted'))
    result['contexts'][0]['context'][3] = 0.
    assert request == original
    assert subject.verify_native768_contexts(retained['manifest_ref'], sources=request)['contexts'][0]['context'][3] == 1.


@pytest.mark.parametrize('damage', ['text', 'id', 'target', 'duplicate', 'empty', 'custom'])
def test_requested_sources_have_exact_target_free_identity(retained, damage):
    rows = _request(retained, 'train')
    if damage == 'text': rows[0]['source_text'] += ' substituted'
    if damage == 'id': rows[0]['id'] = 'absent'
    if damage == 'target': rows[0]['canonical_ir'] = {}
    if damage == 'duplicate': rows.append(deepcopy(rows[0]))
    if damage == 'empty': rows = []
    if damage == 'custom': rows[0] = type('Custom', (dict,), {})(rows[0])
    with pytest.raises(ValueError):
        subject.verify_native768_contexts(retained['manifest_ref'], sources=rows)


@pytest.mark.parametrize('damage', ['vector', 'swap', 'id', 'missing', 'extra', 'stage', 'origin', 'upstream'])
def test_rehashed_context_without_original_producer_join_is_rejected(retained, damage):
    representation = retained['manifest']['representations']['native768']
    rows = _load(representation['contexts']['train'])
    row = rows[0]
    if damage == 'vector': row['context'] = [0., 1.] + [0.] * 766
    if damage == 'swap': rows = _load(representation['contexts']['tuning'])
    if damage == 'id': row['id'] = 'renamed'
    if damage == 'missing': rows = []
    if damage == 'extra': rows.append(deepcopy(row))
    if damage == 'stage': row['native_stage_receipt']['stage'] = 'trained384'
    if damage == 'origin': row['native_stage_receipt']['cache_reused'] = False
    if damage == 'upstream': row['native_stage_receipt']['upstream_receipt_sha256'] = '0' * 64
    for row in rows:
        row['context_sha256'] = subject.digest(row['context'])
        row['native_stage_receipt']['vector_sha256'] = row['context_sha256']
        row['native_stage_receipt']['receipt_sha256'] = subject.digest({k: v for k, v in row['native_stage_receipt'].items() if k != 'receipt_sha256'})
    representation['contexts']['train'] = _save(retained['path'] / 'contexts-train.json', rows)
    with pytest.raises(ValueError):
        subject.verify_native768_contexts(_repin_manifest(retained), sources=_request(retained, 'train'))


@pytest.mark.parametrize('damage', ['bool_dimension', 'selection', 'count', 'lineage', 'assets', 'configuration'])
def test_repinned_manifest_cannot_break_complete_provenance(retained, damage):
    manifest = retained['manifest']
    if damage == 'bool_dimension': manifest['representations']['native768']['dimension'] = True
    if damage == 'selection': manifest['selected_source_sha256'].pop()
    if damage == 'count': manifest['context_count'] = 3
    if damage == 'lineage': manifest['representations']['native768']['lineage_artifacts'].pop()
    if damage == 'assets':
        value = _load(retained['config']['asset_manifest'])
        value['files'][0]['sha256'] = '0' * 64
        # Keep its independent original hash; changing the manifest cannot
        # replace the separately pinned configuration's asset commitment.
        _save(Path(retained['config']['asset_manifest']['path']), value)
    if damage == 'configuration':
        value = deepcopy(retained['config'])
        value['sources'] = {}
        manifest['configuration'] = _save(retained['path'] / 'configuration.json', value)
    with pytest.raises(ValueError):
        subject.verify_native768_contexts(_repin_manifest(retained), sources=_request(retained, 'train'))


def test_all_context_files_are_replayed_even_when_one_source_is_requested(retained):
    reference = retained['manifest']['representations']['native768']['contexts']['oov']
    Path(reference['path']).write_text('{}')
    with pytest.raises(ValueError):
        subject.verify_native768_contexts(retained['manifest_ref'], sources=_request(retained, 'train'))


@pytest.mark.parametrize('field,value', [('embedding', [True] + [0.] * 767),
    ('embedding', [float('inf')] + [0.] * 767), ('dimension', True),
    ('token_count_including_special_tokens', True), ('truncated', True)])
def test_native_receipt_scalar_types_and_profile_are_exact(retained, field, value):
    receipt = deepcopy(retained['report']['receipts'][0])
    receipt[field] = value
    with pytest.raises(ValueError):
        subject.valid_native_receipt(receipt, profile_id=retained['producer'].PROFILE_ID,
            asset_sha256=retained['config']['asset_manifest']['sha256'])


def test_final_fence_rejects_configuration_changed_after_initial_replay(retained, monkeypatch):
    original = subject._assets_and_execution
    def change_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(retained['manifest']['configuration']['path']).write_text('{}')
        return result
    monkeypatch.setattr(subject, '_assets_and_execution', change_after_read)
    with pytest.raises(ValueError, match='changed'):
        subject.verify_native768_contexts(retained['manifest_ref'], sources=_request(retained, 'train'))


def test_duplicate_json_keys_are_rejected_before_replay(retained):
    path = retained['path'] / 'duplicate.json'
    path.write_bytes(b'{"schema":1,"schema":2}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        subject.verify_native768_contexts(subject.ref(path), sources=_request(retained, 'train'))


def test_mutating_caller_manifest_reference_during_replay_is_rejected(retained, monkeypatch):
    previous = subject._native_manifest
    def mutate(reference):
        result = previous(reference)
        retained['manifest_ref']['sha256'] = '0' * 64
        return result
    monkeypatch.setattr(subject, '_native_manifest', mutate)
    with pytest.raises(ValueError, match='manifest reference changed'):
        subject.verify_native768_contexts(retained['manifest_ref'], sources=_request(retained, 'train'))


def test_native_artifact_join_reaches_real_source_batch_binding(retained):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_context_binding as binding
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import CheckpointContentGuard
    digest = lambda value: CheckpointContentGuard(value).sha256
    sources = _request(retained, 'train')
    rows = [{**sources[0], 'canonical_ir': {'rules': [{'modality': 'O', 'actor': 'agency',
        'action': 'disclose', 'object': 'records', 'conditions': [], 'exceptions': [], 'temporal': []}]}}]
    manifest = splits.LegalIRSplitManifest(
        examples=(splits.LegalIRSplitExample.from_sample({'sample_id': 'train', 'text': rows[0]['source_text']}),),
        assignments={'train': 'train'}, config_digest='a' * 64).to_dict()
    exact = dict(id='train', source_text_sha256=hashlib.sha256(rows[0]['source_text'].encode()).hexdigest(),
                 canonical_ir_sha256=digest(rows[0]['canonical_ir']))
    eligibility = [{**exact, 'target_origin': 'authored_engineering_fixture', 'status': 'eligible',
        'allowed_operations': ['training'], 'reason': 'Fictional artifact integration fixture.'}]
    exposure = [{**exact, 'target_exposure': 'declared_supervised_training', 'provenance_ref': 'fixture:authored'}]
    original = subject.verify_native768_contexts(retained['manifest_ref'], sources=sources)
    contexts = [{k: row[k] for k in ('id', 'source_sha256', 'context')} for row in original['contexts']]
    common = dict(split_manifest=manifest, eligibility_records=eligibility, exposure_records=exposure,
                  contexts=contexts, context_evidence=retained['manifest_ref'])
    prepared = binding.prepare_source_span_context_binding(rows, **common,
        expected_rows_sha256=digest(rows), expected_split_manifest_sha256=digest(manifest),
        expected_eligibility_sha256=digest(eligibility), expected_exposure_sha256=digest(exposure),
        expected_contexts_sha256=digest(contexts), expected_context_evidence_sha256=digest(retained['manifest_ref']),
        operation='training', stage='native768')
    received = []
    binding.consume_source_span_context_binding(prepared, rows, **common, consumer=received.append)
    assert received == [[{**rows[0], 'latent': contexts[0]['context']}]]
    Path(retained['manifest']['producer_reports'][0]['path']).write_text('{}')
    with pytest.raises(binding.SourceSpanContextBindingError):
        binding.consume_source_span_context_binding(prepared, rows, **common, consumer=received.append)
    assert len(received) == 1

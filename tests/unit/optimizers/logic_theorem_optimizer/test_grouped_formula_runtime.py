"""Explicit grouped registry routing and actual owner restoration, not accuracy."""
from copy import deepcopy
import hashlib
import json

import pytest
import torch

from ipfs_datasets_py.logic.deontic import coordination_decoder as semantic
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as registry


VERSION = 'source_conditioned_grouped_v2'
SOURCE = 'The Clerk shall publish notice or shall retain records.'


@pytest.fixture(scope='module', autouse=True)
def cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope='module')
def checkpoint():
    model = head.GroupedSpanDecoder(head.SpanDecoderConfig(
        seed=17, byte_dim=4, byte_hidden=4, token_dim=8, token_hidden=8, slot_hidden=8))
    optimizer = head.make_grouped_span_optimizer(model)
    return head.save_grouped_span_checkpoint(model, optimizer, steps=0)


def write_checkpoint(tmp_path, checkpoint):
    path = tmp_path / 'grouped.json'
    raw = json.dumps(checkpoint, allow_nan=False).encode()
    path.write_bytes(raw)
    return {'checkpoint_path': path, 'checkpoint_sha256': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def runtime(tmp_path, checkpoint):
    return registry.open_runtime('legal_ir', VERSION, **write_checkpoint(tmp_path, checkpoint))


def controlled_heads(model, *, scope='modal_over_actions', support=20.0, modality='O'):
    tokens = head.tokenize_source(SOURCE, model.config)
    starts, ends = {token.start: i for i, token in enumerate(tokens)}, {token.end: i for i, token in enumerate(tokens)}
    values = {'support': torch.tensor([support], dtype=torch.float32),
              'count': torch.full((1, 7), -100.0), 'scope': torch.full((1, 2), -100.0),
              'modality': torch.full((1, 8, 3), -100.0)}
    values.update({key: torch.full((1, 8, len(tokens)), -100.0) for key in head.POINTERS})
    values['count'][0, 0] = 100.0
    values['scope'][0, head.SCOPES.index(scope)] = 100.0
    for slot, action in enumerate(('publish notice', 'retain records')):
        values['modality'][0, slot, head.MODALITIES.index(modality)] = 100.0
        for field, span in {'actor': (4, 9), 'action': (SOURCE.index(action), SOURCE.index(action) + len(action))}.items():
            values[field + '_start'][0, slot, starts[span[0]]] = 100.0
            values[field + '_end'][0, slot, ends[span[1]]] = 100.0
    return values


def assert_no_authority(result):
    for key in ('accepted', 'qualified', 'admitted', 'formalized', 'promotion_performed',
                'source_semantics_verified', 'proof_ready', 'kernel_checked', 'lake_executed',
                'model_accuracy_claimed', 'targets_used_at_inference', 'latent_conditioned'):
        assert result[key] is False, key
    assert result['experimental'] is result['requires_validation'] is True


def test_explicit_profile_preserves_all_previous_runtime_selections():
    catalog = registry.list_runtimes()
    selected = [row for row in catalog if row['runtime_version'] == VERSION]
    assert len(selected) == 1 and selected[0]['domain'] == 'legal_ir'
    descriptor = selected[0]
    assert descriptor['dimension'] is None
    assert descriptor['numeric_vector_conditioning'] is False
    assert descriptor['input_fields'] == ['source_text', 'modal_scope']
    assert descriptor['state_schema'] == head.CHECKPOINT_SCHEMA
    assert descriptor['output_schema'] == semantic.COORDINATION_DECODE_REQUEST_SCHEMA
    assert descriptor['capabilities'] == ['load_checkpoint', 'infer', 'decode_formal_logic']
    assert descriptor['supported_logic_families'] == ['deontic_fol']
    assert descriptor['all_family_requirements_satisfied'] is False
    assert len(descriptor['qualification_requirements']['logic_floor']) == 8
    assert descriptor['qualification_requirements']['qualified'] is False
    assert descriptor['formal_decoder']['member_count'] == {'minimum': 2, 'maximum': 8}
    assert registry.describe_runtime('legal_ir', 'legacy_v1')['dimension'] == 8
    assert registry.describe_runtime('legal_ir', 'current_v2')['dimension'] == 384
    assert registry.describe_runtime('legal_ir', registry.LEARNED_FORMULA_VERSION)['state_schema'] == 'learned-legal-formula-checkpoint/v1'
    for domain in registry.NATIVE_DOMAINS:
        assert VERSION not in {row['runtime_version'] for row in catalog if row['domain'] == domain}


@pytest.mark.parametrize('domain,version', [('intent_ir', VERSION), ('security_ir', VERSION),
    ('ui_ux_ir', VERSION), ('codebase_ir', VERSION), ('legal_ir', 'source_conditioned_grouped_v1'),
    ('legal_ir', '768'), ('legal_ir', 'source_conditioned_grouped_v3')])
def test_wrong_domain_or_version_never_opens_grouped_model(domain, version, monkeypatch):
    monkeypatch.setattr(head, 'restore_grouped_span_checkpoint', lambda _: pytest.fail('unexpected restore'))
    with pytest.raises(registry.RuntimeVersionError, match='unknown'):
        registry.open_runtime(domain, version)


def test_strict_restore_matches_all_parameters_and_actual_owner_prediction(runtime, checkpoint):
    original, _, steps = head.restore_grouped_span_checkpoint(checkpoint)
    assert steps == runtime.describe()['optimizer_steps'] == 0
    assert all(torch.equal(value, runtime._model.state_dict()[key]) for key, value in original.state_dict().items())
    expected = head.predict_grouped_span_decoder(original, SOURCE, 'modal_over_actions')
    actual = runtime.infer(SOURCE, modal_scope='modal_over_actions')
    assert {key: actual[key] for key in expected} == expected
    assert_no_authority(actual)
    assert runtime.describe()['trained_checkpoint_present'] is False
    assert not hasattr(runtime, 'train') and not hasattr(runtime, 'register_candidate')
    with pytest.raises(registry.RuntimeVersionError, match='lacks registry'):
        registry.load_version(None, 'unused', domain='legal_ir', version=VERSION)
    with pytest.raises(registry.RuntimeVersionError, match='lacks prepare_targets'):
        registry.prepare_targets('legal_ir', VERSION, document={})


def test_local_path_and_exact_file_hash_required_before_numerical_restore(tmp_path, checkpoint, monkeypatch):
    binding = write_checkpoint(tmp_path, checkpoint)
    monkeypatch.setattr(head, 'restore_grouped_span_checkpoint', lambda _: pytest.fail('unexpected restore'))
    with pytest.raises(TypeError):
        registry.open_runtime('legal_ir', VERSION)
    with pytest.raises(registry.RuntimeVersionError, match='local path'):
        registry.open_runtime('legal_ir', VERSION, checkpoint_path=checkpoint, checkpoint_sha256=binding['checkpoint_sha256'])
    for sha in (None, True, 'a' * 63, 'Z' * 64):
        with pytest.raises(registry.RuntimeVersionError, match='exact SHA'):
            registry.open_runtime('legal_ir', VERSION, checkpoint_path=binding['checkpoint_path'], checkpoint_sha256=sha)
    with pytest.raises(registry.RuntimeVersionError, match='mismatch'):
        registry.open_runtime('legal_ir', VERSION, **{**binding, 'checkpoint_sha256': '0' * 64})


@pytest.mark.parametrize('raw', [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_duplicate_and_nonfinite_json_rejected_even_with_matching_file_hash(tmp_path, raw, monkeypatch):
    path = tmp_path / 'malformed.json'
    path.write_bytes(raw)
    monkeypatch.setattr(head, 'restore_grouped_span_checkpoint', lambda _: pytest.fail('unexpected restore'))
    with pytest.raises(registry.RuntimeVersionError, match='duplicate|nonfinite'):
        registry.open_runtime('legal_ir', VERSION, checkpoint_path=path, checkpoint_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('field,value', [('schema', 'legal-grouped-span-decoder-checkpoint/v1'),
                                       ('producer', {}), ('profile', {}), ('checkpoint_sha256', '0' * 64)])
def test_matching_outer_file_hash_cannot_bypass_strict_v2_checkpoint_validation(tmp_path, checkpoint, field, value):
    modified = deepcopy(checkpoint)
    modified[field] = value
    with pytest.raises(ValueError):
        registry.open_runtime('legal_ir', VERSION, **write_checkpoint(tmp_path, modified))


@pytest.mark.parametrize('extra', [{'target_request': {}}, {'members': []}, {'embedding': [0.0] * 768},
                                  {'dimension': 768}, {'proof_ready': True}])
def test_closed_inference_rejects_targets_vectors_and_authority_inputs(runtime, extra, monkeypatch):
    monkeypatch.setattr(runtime._model, 'forward', lambda *_: pytest.fail('unexpected forward'))
    with pytest.raises(TypeError):
        runtime.infer(SOURCE, modal_scope='modal_over_actions', **extra)
    with pytest.raises(registry.RuntimeVersionError, match='raw source_text'):
        runtime.infer({'source_text': SOURCE, 'modal_scope': 'modal_over_actions'})


@pytest.mark.parametrize('scope', [None, 'unknown', True])
def test_missing_or_unknown_scope_preserves_null_abstention_without_model_or_renderer(runtime, scope, monkeypatch):
    monkeypatch.setattr(runtime._model, 'forward', lambda *_: pytest.fail('unexpected forward'))
    monkeypatch.setattr(semantic, 'decode_coordination_request', lambda _: pytest.fail('unexpected renderer'))
    result = runtime.decode_formal_logic(SOURCE, modal_scope=scope)
    assert result['status'] == 'abstained'
    assert result['request'] is result['formal_output'] is None
    assert result['blockers'] == ['explicit_caller_scope_required']
    assert result['formula_count'] == 0 and result['decoded_formulas_generated'] is False
    assert_no_authority(result)


@pytest.mark.parametrize('scope', head.SCOPES)
@pytest.mark.parametrize('modality', head.MODALITIES)
def test_actual_closed_request_renderer_has_only_deontic_syntax_and_no_admission(runtime, scope, modality, monkeypatch):
    values = controlled_heads(runtime._model, scope=scope, modality=modality)
    monkeypatch.setattr(runtime._model, 'forward', lambda *_: values)
    result = runtime.decode_formal_logic(SOURCE, modal_scope=scope)
    assert result['status'] == 'predicted'
    assert [member['action'] for member in result['request']['members']] == ['publish notice', 'retain records']
    assert [member['modality'] for member in result['request']['members']] == [modality, modality]
    assert result['request']['modal_scope'] == scope
    assert result['formula_count'] == 1 and result['decoded_formulas_generated'] is True
    formal = result['formal_output']
    assert formal == semantic.decode_coordination_request(semantic.CoordinationDecodeRequest.from_dict(result['request']))
    assert formal['target_logic'] == 'deontic_fol'
    assert formal['family_validation']['passed'] is True
    assert formal['lean_body'] and formal['native_ast']
    assert result['blockers'] == ['source_interpretation_unreviewed']
    assert formal['source_semantics_verified'] is formal['proof_ready'] is formal['admitted'] is False
    assert_no_authority(result)


@pytest.mark.parametrize('kind', ['learned_refusal', 'scope_mismatch', 'malformed_head'])
def test_actual_neural_refusal_or_block_never_calls_renderer(runtime, kind, monkeypatch):
    values = controlled_heads(runtime._model, support=-20.0 if kind == 'learned_refusal' else 20.0,
                              scope='disjunction_of_norms' if kind == 'scope_mismatch' else 'modal_over_actions')
    if kind == 'malformed_head':
        del values['scope']
    monkeypatch.setattr(runtime._model, 'forward', lambda *_: values)
    monkeypatch.setattr(semantic, 'decode_coordination_request', lambda _: pytest.fail('unexpected renderer'))
    result = runtime.decode_formal_logic(SOURCE, modal_scope='modal_over_actions')
    expected = {'learned_refusal': 'learned_source_unsupported',
                'scope_mismatch': 'predicted_scope_disagrees_with_caller', 'malformed_head': 'malformed_model_prediction'}
    assert result['blockers'] == [expected[kind]]
    assert result['request'] is result['formal_output'] is None
    assert result['formula_count'] == 0
    assert_no_authority(result)


def test_common_formal_factory_uses_only_explicit_new_profile(tmp_path, checkpoint):
    runtime = registry.open_formal_decoder('legal_ir', VERSION, **write_checkpoint(tmp_path, checkpoint))
    assert type(runtime) is registry.GroupedFormulaRuntime
    assert runtime.describe()['runtime_id'] == 'legal_ir:' + VERSION

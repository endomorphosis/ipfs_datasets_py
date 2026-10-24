"""Authored companion custody tests; no statutory accuracy or training claims."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_decoder_example_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as compact


def fixture_module():
    """Reuse existing authored public-owner fixtures, never a new source join."""
    path = Path(__file__).with_name('test_legal_relational_decoder_example_v1.py')
    spec = importlib.util.spec_from_file_location('_compact_companion_existing_example_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


examples = fixture_module()
joins = examples.fixtures


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_case(*, request=None, pretty=False, source=None, **typed):
    value = joins.case(source=source, **typed)
    if pretty:
        canonical = value['kwargs']['relational_request_raw']
        assert canonical is not None
        raw = (json.dumps(json.loads(canonical), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        value['kwargs']['relational_request_raw'] = raw
        value['kwargs']['expected_relational_request_sha256'] = sha(raw)
        value['relational_report'] = joins.relational.prepare_relational_norm_v1(raw,
            expected_request_sha256=sha(raw))
        value['kwargs']['expected_relational_report_sha256'] = joins.relational.relational_norm_report_sha256(
            value['relational_report'])
    join_report = joins.prepare(value)
    options = examples.arguments(value, request=request)
    source_example = examples.subject.prepare_relational_decoder_example_v1(join_report, **options)
    return {'value': value, 'join': join_report, 'options': options, 'source': source_example}


@pytest.fixture(scope='module')
def authored_base():
    return make_case()


def arguments(case):
    options = deepcopy(case['options'])
    raw = options.pop('example_request_raw')
    options['expected_source_example_sha256'] = examples.subject.relational_decoder_example_sha256(case['source'])
    return (case['source'], case['join'], raw), options


def prepare(case, *, changes=None):
    args, options = arguments(case)
    if changes:
        options.update(changes)
    return subject.prepare_compact_decoder_example_v1(*args, **options)


def validate(report, case, *, changes=None):
    args, options = arguments(case)
    options['expected_report_sha256'] = sha(wire(report))
    if changes:
        options.update(changes)
    return subject.validate_compact_decoder_example_v1(report, *args, **options)


def no_authority(report):
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
    assert report['authority'] and all(value is False for value in report['authority'].values())
    base = report['source_example']
    assert base['split'] == 'unassigned'
    assert base['training_mask'] == base['evaluation_gold_mask'] == 0
    assert all(value is False for value in base['authority'].values())
    if report['compact_label'] is not None:
        projection = report['compact_label']
        assert projection['training_mask'] == projection['evaluation_gold_mask'] == 0
        assert all(value is False for value in projection['authority'].values())
        assert projection['normalization']['permitted_inference_context_verified'] is False


def test_full_public_replay_preserves_source_example_and_complete_old_byte_label(authored_base):
    case = deepcopy(authored_base)
    before = deepcopy(case)
    report = prepare(case)
    assert set(report) == {'schema', 'profile', 'source_example', 'source_example_sha256', 'compact_label',
                           'producer_pins', 'authority', 'training_mask', 'evaluation_gold_mask', 'limitations'}
    assert report['schema'] == 'legal-compact-decoder-example/v1'
    assert report['profile'] == 'candidate-source-separated-compact-content/v1'
    assert report['source_example'] == case['source']
    assert report['source_example_sha256'] == sha(wire(case['source']))
    assert validate(report, case) == report
    assert subject.compact_decoder_example_sha256(report) == sha(wire(report))
    raw = case['value']['kwargs']['relational_request_raw']
    expected_projection = compact.project_request_v1(raw, expected_request_sha256=sha(raw))
    assert report['compact_label'] == expected_projection
    preserved = report['source_example']
    assert set(preserved['model_input']) == {'source_text', 'context'}
    assert wire(preserved['model_input']) == wire(case['source']['model_input'])
    assert preserved['source_input_sha256'] == sha(wire(preserved['model_input']))
    assert preserved['label'] == case['source']['label']
    old_encoding = preserved['label']['encoding']
    assert old_encoding['target_ids'] == [1, *(3 + value for value in old_encoding['canonical_request_raw_utf8'].encode('utf-8')), 2]
    assert old_encoding['original_request']['sha256'] == expected_projection['original_request_raw_sha256']
    assert old_encoding['canonical_request']['sha256'] == expected_projection['original_request_sha256']
    assert old_encoding['relational_owner_report_sha256'] == preserved['label']['relational_report_sha256']
    assert preserved['producer_pins'].items() <= report['producer_pins'].items()
    assert {row['path']: row['sha256'] for row in expected_projection['owner_pins']}.items() <= report['producer_pins'].items()
    assert case == before
    no_authority(report)


@pytest.mark.parametrize('change', ['modal_letter', 'modal_scope', 'argument_order'])
def test_distinct_authored_alternatives_keep_same_source_input_and_physical_group(authored_base, change):
    options = {'operator': 'O'} if change == 'modal_letter' else (
        {'inside_modal': True} if change == 'modal_scope' else {'swapped_arguments': True})
    first = prepare(deepcopy(authored_base))
    other = make_case(**options)
    other['value']['join_request']['alternative_id'] = 'fictional:alternative:' + change
    other['join'] = joins.prepare(other['value'])
    other['options'] = examples.arguments(other['value'])
    other['source'] = examples.subject.prepare_relational_decoder_example_v1(other['join'], **other['options'])
    second = prepare(other)
    for field in ('model_input', 'source_input_sha256', 'source_identity', 'source_group_sha256'):
        assert second['source_example'][field] == first['source_example'][field]
    assert second['source_example']['provenance']['alternative_id'] != first['source_example']['provenance']['alternative_id']
    assert second['compact_label']['content'] != first['compact_label']['content']
    assert second['source_example']['label']['encoding']['target_ids'] != first['source_example']['label']['encoding']['target_ids']
    assert set(second['source_example']['model_input']) == {'source_text', 'context'}
    no_authority(first)
    no_authority(second)


def test_identical_authored_text_at_two_physical_occurrences_stays_two_source_groups():
    source = joins.source_case(duplicate=True)
    left, right = deepcopy(source), deepcopy(source)
    left['unit'], right['unit'] = source['units'][0], source['units'][1]
    first, second = prepare(make_case(source=left)), prepare(make_case(source=right))
    assert first['source_example']['model_input'] == second['source_example']['model_input']
    assert first['compact_label']['content'] == second['compact_label']['content']
    assert first['source_example']['source_identity']['span_sha256'] == second['source_example']['source_identity']['span_sha256']
    assert first['source_example']['source_identity']['start_char'] != second['source_example']['source_identity']['start_char']
    assert first['source_example']['source_group_sha256'] != second['source_example']['source_group_sha256']


def test_source_only_pending_has_no_compact_target_and_never_invokes_projection(monkeypatch):
    case = make_case(source_only=True, request=examples.example_request(exposure='unknown'))
    def forbidden(*args, **kwargs):
        pytest.fail('pending source must not manufacture or project a target')
    monkeypatch.setattr(compact, 'project_request_v1', forbidden)
    report = prepare(case)
    assert validate(report, case) == report
    assert report['compact_label'] is None and report['source_example']['label'] is None
    assert report['source_example'] == case['source']
    assert report['source_example']['status'] == 'source_only_pending_target'
    assert report['source_example']['provenance']['introduced_unresolved'] == []
    assert report['source_example']['provenance']['exposure_status'] == 'unknown'
    no_authority(report)


def test_pretty_original_transport_keeps_raw_and_canonical_bindings_and_archival_inverse():
    case = make_case(pretty=True)
    report = prepare(case)
    old = report['source_example']['label']
    projection = report['compact_label']
    raw = old['request_raw_utf8'].encode('utf-8')
    canonical = wire(json.loads(raw))
    assert raw != canonical and sha(raw) != sha(canonical)
    assert old['request_raw_sha256'] == projection['original_request_raw_sha256'] == sha(raw)
    assert old['encoding']['canonical_request']['sha256'] == projection['original_request_sha256'] == sha(canonical)
    content, context, identity = map(wire, (projection['content'], projection['context'], projection['identity_sidecar']))
    restored = compact.reconstruct_request_v1(content, context, identity,
        expected_content_sha256=sha(content), expected_context_sha256=sha(context),
        expected_identity_sha256=sha(identity), expected_original_request_sha256=sha(canonical))
    assert restored['request'] == json.loads(raw)
    assert restored['identity_mode'] == 'restored'
    assert validate(report, case) == report
    no_authority(report)


@pytest.mark.parametrize('dimension', [8, 384, 768])
def test_embedding_lane_declaration_stays_outside_source_input_and_is_not_authenticated(authored_base, dimension):
    case = deepcopy(authored_base)
    reference = examples.embedding_reference(case['value'], dimension)
    case['options'] = examples.arguments(case['value'], request=examples.example_request(reference))
    case['source'] = examples.subject.prepare_relational_decoder_example_v1(case['join'], **case['options'])
    report = prepare(case)
    assert report['source_example']['embedding_reference'] == reference
    assert report['source_example']['model_input'] == authored_base['source']['model_input']
    assert report['source_example']['source_group_sha256'] == authored_base['source']['source_group_sha256']
    assert report['source_example']['label'] == authored_base['source']['label']
    for field in ('embedding_payload_verified', 'embedding_producer_verified', 'embedding_source_independence_verified'):
        assert report['source_example']['authority'][field] is False
    no_authority(report)


@pytest.mark.parametrize('exposure', ['exposed', 'unknown'])
def test_exposure_remains_caller_declared_unassigned_and_unqualified(authored_base, exposure):
    case = deepcopy(authored_base)
    case['options'] = examples.arguments(case['value'], request=examples.example_request(exposure=exposure))
    case['source'] = examples.subject.prepare_relational_decoder_example_v1(case['join'], **case['options'])
    report = prepare(case)
    assert report['source_example']['provenance']['exposure_status'] == exposure
    assert report['source_example']['provenance']['exposure_status_caller_declared'] is True
    assert report['source_example']['split'] == 'unassigned'
    assert report['compact_label']['normalization']['permitted_inference_context_verified'] is False
    no_authority(report)


@pytest.mark.parametrize('damage', ['target_in_input', 'source_text', 'old_label', 'source_group', 'source_identity',
                                  'provenance', 'authority', 'training_mask', 'gold_mask', 'split', 'producer_pin'])
def test_resealed_source_example_cannot_bypass_original_full_public_replay(authored_base, damage):
    case = deepcopy(authored_base)
    source = case['source']
    if damage == 'target_in_input': source['model_input']['target'] = deepcopy(source['label'])
    elif damage == 'source_text': source['model_input']['source_text'] += ' invented meaning'
    elif damage == 'old_label': source['label']['encoding']['target_ids'][1] = 3 + ord('[')
    elif damage == 'source_group': source['source_group_sha256'] = '0' * 64
    elif damage == 'source_identity': source['source_identity']['start_char'] += 1
    elif damage == 'provenance': source['provenance']['provenance_ledger'].pop()
    elif damage == 'authority': source['authority']['training_qualified'] = True
    elif damage == 'training_mask': source['training_mask'] = 1
    elif damage == 'gold_mask': source['evaluation_gold_mask'] = 1
    elif damage == 'split': source['split'] = 'test'
    else: source['producer_pins'][next(iter(source['producer_pins']))] = '0' * 64
    # The independently offered report commitment is deliberately resealed;
    # original source/join/codec inputs still have their original commitments.
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize('damage', ['source_example', 'source_hash', 'content', 'context', 'sidecar', 'counts',
                                  'original_raw_hash', 'canonical_hash', 'producer_pin', 'authority',
                                  'training_mask', 'gold_mask', 'extra_field'])
def test_resealed_companion_cannot_substitute_nested_labels_or_promote_authority(authored_base, damage):
    case = deepcopy(authored_base)
    report = prepare(case)
    if damage == 'source_example': report['source_example']['model_input']['source_text'] += ' replacement'
    elif damage == 'source_hash': report['source_example_sha256'] = '0' * 64
    elif damage == 'content': report['compact_label']['content']['tree'][0] = 'exists'
    elif damage == 'context': report['compact_label']['context']['argument_roles'][0]['roles'].reverse()
    elif damage == 'sidecar': report['compact_label']['identity_sidecar']['node_ids'][0] += ':changed'
    elif damage == 'counts': report['compact_label']['counts']['nodes'] += 1
    elif damage == 'original_raw_hash': report['compact_label']['original_request_raw_sha256'] = '0' * 64
    elif damage == 'canonical_hash': report['compact_label']['original_request_sha256'] = '0' * 64
    elif damage == 'producer_pin': report['producer_pins'][next(iter(report['producer_pins']))] = '0' * 64
    elif damage == 'authority': report['authority'][next(iter(report['authority']))] = True
    elif damage == 'training_mask': report['training_mask'] = 1
    elif damage == 'gold_mask': report['evaluation_gold_mask'] = 1
    else: report['model_input'] = deepcopy(report['source_example']['model_input'])
    with pytest.raises(ValueError): validate(report, case)


@pytest.mark.parametrize('bad_hash', ['0' * 64, 'A' * 64, None, True])
def test_source_report_commitment_refuses_before_loading_operation_owners(authored_base, monkeypatch, bad_hash):
    case = deepcopy(authored_base)
    args, options = arguments(case)
    options['expected_source_example_sha256'] = bad_hash
    monkeypatch.setattr(subject, '_owners', lambda: pytest.fail('owners loaded before source commitment refusal'))
    with pytest.raises(ValueError): subject.prepare_compact_decoder_example_v1(*args, **options)


@pytest.mark.parametrize('bad_hash', ['0' * 64, 'A' * 64, None])
def test_complete_companion_commitment_refuses_before_loading_operation_owners(authored_base, monkeypatch, bad_hash):
    case = deepcopy(authored_base)
    report = prepare(case)
    args, options = arguments(case)
    monkeypatch.setattr(subject, '_owners', lambda: pytest.fail('owners loaded before complete report commitment refusal'))
    with pytest.raises(ValueError):
        subject.validate_compact_decoder_example_v1(report, *args, expected_report_sha256=bad_hash, **options)


def test_public_cold_import_and_digest_use_only_stdlib(monkeypatch):
    module = ModuleType('_cold_compact_decoder_example')
    module.__file__ = subject.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ordinary_import = builtins.__import__
    attempted = []
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in {'ipfs_datasets_py', 'torch', 'numpy', 'transformers', 'requests',
                                 'pyarrow', 'duckdb', 'cryptography', 'huggingface_hub'}:
            attempted.append(name)
            raise AssertionError('operation owner imported by pure public boundary')
        return ordinary_import(name, *args, **kwargs)
    source = Path(subject.__file__).read_bytes()
    with monkeypatch.context() as context:
        context.setattr(builtins, '__import__', guarded)
        exec(compile(source, module.__file__, 'exec', dont_inherit=True, optimize=0), module.__dict__)
        assert module.compact_decoder_example_sha256({'ordinary': True}) == sha(wire({'ordinary': True}))
    assert attempted == []


@pytest.mark.parametrize('damage', ['nonfinite', 'nonstring_key', 'opaque', 'cycle'])
def test_digest_rejects_nonordinary_or_cyclic_input_without_owner_import(monkeypatch, damage):
    offered = {'value': float('nan')} if damage == 'nonfinite' else (
        {1: 'not-a-string-key'} if damage == 'nonstring_key' else {'value': object()})
    if damage == 'cycle':
        offered = []
        offered.append(offered)
    monkeypatch.setattr(subject, '_owners', lambda: pytest.fail('digest loaded operation owners'))
    with pytest.raises(ValueError): subject.compact_decoder_example_sha256(offered)


def test_whole_report_digest_overflow_refuses_without_truncation_or_owners(monkeypatch):
    monkeypatch.setattr(subject, '_owners', lambda: pytest.fail('whole bound loaded operation owners'))
    offered = {'oversize': 'x' * (subject.MAX_REPORT_BYTES + 1)}
    with pytest.raises(ValueError): subject.compact_decoder_example_sha256(offered)


def test_whole_source_example_bound_refuses_before_owner_loading(authored_base, monkeypatch):
    case = deepcopy(authored_base)
    args, options = arguments(case)
    args[0]['whole_oversize'] = 'x' * (subject.MAX_SOURCE_EXAMPLE_BYTES + 1)
    options['expected_source_example_sha256'] = sha(wire(args[0]))
    monkeypatch.setattr(subject, '_owners', lambda: pytest.fail('source bound loaded operation owners'))
    with pytest.raises(ValueError): subject.prepare_compact_decoder_example_v1(*args, **options)


def test_outputs_and_source_inputs_are_detached_across_calls(authored_base):
    case = deepcopy(authored_base)
    before = deepcopy(case)
    first = prepare(case)
    pristine = deepcopy(first)
    first['source_example']['model_input']['source_text'] += ' mutation'
    first['compact_label']['content']['tree'][0] = 'exists'
    first['compact_label']['identity_sidecar']['node_ids'].reverse()
    first['authority'][next(iter(first['authority']))] = True
    assert case == before
    assert prepare(case) == pristine


@pytest.mark.parametrize('error_type', [OSError, RuntimeError, TimeoutError])
def test_operational_example_replay_errors_propagate_without_becoming_invalid_predictions(authored_base, monkeypatch, error_type):
    case = deepcopy(authored_base)
    def unavailable(*args, **kwargs):
        raise error_type('authored operational replay unavailable')
    monkeypatch.setattr(examples.subject, 'validate_relational_decoder_example_v1', unavailable)
    with pytest.raises(error_type, match='authored operational replay unavailable'):
        prepare(case)


@pytest.mark.parametrize('boundary', ['source_replay', 'compact_projection'])
def test_original_caller_mutation_after_real_owner_callback_is_refused(authored_base, monkeypatch, boundary):
    case = deepcopy(authored_base)
    if boundary == 'source_replay':
        owner, name = examples.subject, 'validate_relational_decoder_example_v1'
    else:
        owner, name = compact, 'project_request_v1'
    original = getattr(owner, name)
    calls = []
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        case['source']['model_input']['source_text'] += ' mutation after real callback'
        return result
    monkeypatch.setattr(owner, name, changed)
    with pytest.raises(ValueError): prepare(case)
    assert calls == [True]


def test_validated_producer_drift_after_real_projection_is_refused_by_integrity_seam(authored_base, monkeypatch):
    """Simulate a later source observation, without altering canonical files."""
    case = deepcopy(authored_base)
    watched = next(Path(path) for path in case['source']['producer_pins']
                   if path.endswith('/logic/syntax_core/codec.py'))
    snapshot, project = subject._snapshot, compact.project_request_v1
    armed, observed, calls = [False], [], []
    def changed_snapshot(path):
        state = snapshot(path)
        if armed[0] and Path(path) == watched:
            observed.append(str(path))
            return ('0' * 64, state[1])
        return state
    def arm_after_public_projection(*args, **kwargs):
        result = project(*args, **kwargs)
        calls.append(True)
        armed[0] = True
        return result
    monkeypatch.setattr(subject, '_snapshot', changed_snapshot)
    monkeypatch.setattr(compact, 'project_request_v1', arm_after_public_projection)
    with pytest.raises(ValueError): prepare(case)
    assert calls == [True] and observed


def test_complete_report_serialization_precedes_final_source_fence_integrity_seam(authored_base, monkeypatch):
    """Exercise final serialization/source ordering after real public replay."""
    case = deepcopy(authored_base)
    watched = Path(subject.__file__)
    snapshot, ordinary_wire = subject._snapshot, subject._wire
    armed, serialized, observed = [False], [], []
    def changed_snapshot(path):
        state = snapshot(path)
        if armed[0] and Path(path) == watched:
            observed.append(str(path))
            return ('0' * 64, state[1])
        return state
    def arm_after_complete_serialization(value, *args, **kwargs):
        result = ordinary_wire(value, *args, **kwargs)
        if type(value) is dict and value.get('schema') == subject.SCHEMA:
            serialized.append(True)
            armed[0] = True
        return result
    monkeypatch.setattr(subject, '_snapshot', changed_snapshot)
    monkeypatch.setattr(subject, '_wire', arm_after_complete_serialization)
    with pytest.raises(ValueError): prepare(case)
    assert serialized == [True] and observed


def test_projection_expression_commitment_cannot_be_substituted_at_public_owner_return_seam(authored_base, monkeypatch):
    """Check a cross-owner binding after a genuine successful projection."""
    case = deepcopy(authored_base)
    project = compact.project_request_v1
    observed = []
    def substituted(*args, **kwargs):
        result = project(*args, **kwargs)
        observed.append(result['original_expression_sha256'])
        result['original_expression_sha256'] = '0' * 64
        return result
    monkeypatch.setattr(compact, 'project_request_v1', substituted)
    with pytest.raises(ValueError): prepare(case)
    assert observed == [sha(wire(json.loads(case['value']['kwargs']['relational_request_raw'])['expression']))]


# The counted companion retains the entire original source-only example; its
# target is a separate authored fixed grammar, never an inferred legal meaning.
def _counted_companion_owner():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    return counted


def _counted_companion_case(*, source=None, alternative='fixture:counted-companion:one'):
    counted = _counted_companion_owner()
    old = make_case(source_only=True, source=source)
    request = counted.authored_counted_frame_request()
    request_raw = wire(request)
    counted_report = counted.prepare_counted_frame(request_raw, expected_request_sha256=sha(request_raw))
    inventory = joins._independent_counted_paths(request['expression'])
    code = 'all_counted_frame_semantics_unreviewed'
    raw_join = wire({'schema': 'legal-source-typed-norm-join-request/v2',
        'interpretation_status': 'unreviewed_correspondence_proposal',
        'component_id': 'fixture:counted-companion', 'alternative_id': alternative,
        'selected_unit_ref': deepcopy(old['value']['join_request']['selected_unit_ref']),
        'node_correspondences': [{'typed_path': path, 'source_anchor_paths': [],
            'disposition': 'introduced_unresolved', 'unresolved_codes': [code],
            'rationale': 'Authored syntax nomination with no selected source meaning.'}
            for path, _, _ in inventory],
        'introduced_unresolved': [{'code': code,
            'rationale': 'Carrier, event/time, identity and complete statutory semantics are unreviewed.',
            'affected_typed_paths': [path for path, _, _ in inventory]}]})
    counted_inputs = {'scope_report': deepcopy(old['value']['scope_report']),
        'counted_report': counted_report, 'join_request_raw': raw_join,
        'expected_join_request_sha256': sha(raw_join),
        'expected_scope_report_sha256': old['value']['kwargs']['expected_scope_report_sha256'],
        'expected_counted_report_sha256': counted.counted_frame_report_sha256(counted_report),
        'scope_replay_inputs': deepcopy(old['value']['kwargs']['scope_replay_inputs']),
        'counted_request_raw': request_raw, 'expected_counted_request_sha256': sha(request_raw)}
    counted_join = joins.subject.prepare_source_typed_norm_join_v2(**counted_inputs)
    codec = counted.build_counted_frame_token_codec_v1()
    options = {'expected_source_example_sha256': examples.subject.relational_decoder_example_sha256(old['source']),
        'expected_counted_join_sha256': joins.subject.source_typed_norm_join_sha256(counted_join),
        'source_example_inputs': {'join_report': deepcopy(old['join']), **deepcopy(old['options'])},
        'counted_join_inputs': counted_inputs, 'codec': codec,
        'expected_codec_sha256': counted.counted_frame_token_codec_sha256(codec)}
    return {'source': old['source'], 'counted_join': counted_join, 'options': options,
            'old': old}


@pytest.fixture(scope='module')
def counted_companion_case():
    return _counted_companion_case()


def _counted_companion_prepare(case):
    return subject.prepare_counted_compact_decoder_example_v1(
        case['source'], case['counted_join'], **case['options'])


def _counted_companion_validate(report, case):
    return subject.validate_counted_compact_decoder_example_v1(
        report, case['source'], case['counted_join'],
        expected_report_sha256=subject.compact_decoder_example_sha256(report), **case['options'])


def _assert_counted_companion_limits(report):
    for value in (report, report['source_example'], report['compact_label'], report['compact_encoding']):
        assert value['authority'] and all(flag is False for flag in value['authority'].values())
        assert type(value['training_mask']) is type(value['evaluation_gold_mask']) is int
        assert value['training_mask'] == value['evaluation_gold_mask'] == 0
    assert report['source_example']['split'] == 'unassigned'
    assert report['source_example']['label'] is None
    assert report['source_example']['status'] == 'source_only_pending_target'
    assert report['compact_label']['context_origin'] == 'target_derived_authored_declaration'
    assert report['compact_label']['checkpoint_compatibility_verified'] is False
    assert 'model_input' not in report and 'target' not in report['source_example']['model_input']


def test_counted_companion_calls_all_original_public_owners_and_keeps_source_separate(
        counted_companion_case, monkeypatch):
    case = deepcopy(counted_companion_case)
    calls = []
    for owner, name, label in ((examples.subject, 'validate_relational_decoder_example_v1', 'source'),
            (joins.subject, 'validate_source_typed_norm_join_v2', 'counted_join'),
            (_counted_companion_owner(), 'project_counted_frame_request_v1', 'projection'),
            (_counted_companion_owner(), 'encode_counted_frame_tokens_v1', 'encoding')):
        actual = getattr(owner, name)
        def observed(*args, _actual=actual, _label=label, **kwargs):
            result = _actual(*args, **kwargs)
            calls.append(_label)
            return result
        monkeypatch.setattr(owner, name, observed)
    report = _counted_companion_prepare(case)
    assert _counted_companion_validate(report, case) == report
    assert all(calls.count(name) >= 2 for name in ('source', 'counted_join', 'projection', 'encoding'))
    assert report['schema'] == 'legal-counted-compact-decoder-example/v1'
    assert report['profile'] == 'source-only-example-with-partial-counted-label/v1'
    assert report['ir_family_id'] == 'legal_ir'
    assert report['task_id'] == 'typed_counted_frame_IR_reconstruction'
    assert report['source_example'] == case['source']
    assert report['source_example_sha256'] == sha(wire(case['source']))
    assert report['counted_correspondence'] == case['counted_join']
    assert report['counted_correspondence_sha256'] == sha(wire(case['counted_join']))
    assert set(report['source_example']['model_input']) == {'source_text', 'context'}
    assert report['source_example']['model_input'] == case['old']['value']['scope_report']['scope_request']
    assert len(report['counted_correspondence']['provenance_ledger']) == 55
    assert report['compact_label']['counts'] == {'nodes': 49, 'quantifiers': 6,
        'membership_occurrences': 4, 'equality_occurrences': 6, 'variable_occurrences': 24}
    assert report['compact_encoding']['prediction']['request']['source_binding'] is None
    assert len(report['compact_encoding']['target_ids']) == 293
    assert report['codec_sha256'] == case['options']['expected_codec_sha256']
    _assert_counted_companion_limits(report)


def test_counted_alternatives_share_exact_source_group_without_becoming_independent_cases(
        counted_companion_case):
    left = _counted_companion_prepare(deepcopy(counted_companion_case))
    right_case = _counted_companion_case(alternative='fixture:counted-companion:other')
    right = _counted_companion_prepare(right_case)
    for key in ('model_input', 'source_input_sha256', 'source_identity', 'source_group_sha256'):
        assert left['source_example'][key] == right['source_example'][key]
    assert left['compact_label']['content'] == right['compact_label']['content']
    assert left['counted_correspondence']['alternative_id'] != right['counted_correspondence']['alternative_id']
    _assert_counted_companion_limits(right)


def test_counted_identical_source_text_at_two_physical_occurrences_has_distinct_groups():
    source = joins.source_case(duplicate=True)
    left, right = deepcopy(source), deepcopy(source)
    left['unit'], right['unit'] = source['units'][0], source['units'][1]
    a = _counted_companion_prepare(_counted_companion_case(source=left))
    b = _counted_companion_prepare(_counted_companion_case(source=right))
    assert a['source_example']['model_input'] == b['source_example']['model_input']
    assert a['compact_label']['content'] == b['compact_label']['content']
    assert a['source_example']['source_group_sha256'] != b['source_example']['source_group_sha256']


@pytest.mark.parametrize('damage', ['source_pin', 'counted_pin', 'source_missing', 'source_extra',
    'counted_missing', 'counted_extra', 'codec_pin'])
def test_counted_companion_wrong_pins_or_closed_original_bundles_refuse_before_owner_loading(
        counted_companion_case, monkeypatch, damage):
    case = deepcopy(counted_companion_case)
    options = case['options']
    if damage == 'source_pin': options['expected_source_example_sha256'] = '0' * 64
    elif damage == 'counted_pin': options['expected_counted_join_sha256'] = '0' * 64
    elif damage == 'source_missing': options['source_example_inputs'].pop('join_report')
    elif damage == 'source_extra': options['source_example_inputs']['extra'] = None
    elif damage == 'counted_missing': options['counted_join_inputs'].pop('counted_request_raw')
    elif damage == 'counted_extra': options['counted_join_inputs']['extra'] = None
    else: options['expected_codec_sha256'] = '0' * 64
    monkeypatch.setattr(subject, '_counted_example_owners', lambda: pytest.fail('counted operation owners loaded before pure preflight refusal'))
    with pytest.raises(ValueError):
        _counted_companion_prepare(case)


@pytest.mark.parametrize('different', ['occurrence', 'edition'])
def test_counted_companion_rejects_fully_valid_other_source_even_with_identical_model_text(
        counted_companion_case, different):
    if different == 'occurrence':
        source = joins.source_case(duplicate=True)
        old_source = deepcopy(source)
        old_source['unit'] = source['units'][1]
        other = _counted_companion_case(source=old_source)
        original = _counted_companion_case(source=source)
    else:
        original = deepcopy(counted_companion_case)
        other = _counted_companion_case(source=joins.source_case(edition=2025))
    assert original['source']['model_input'] == other['source']['model_input']
    original['counted_join'] = other['counted_join']
    original['options']['counted_join_inputs'] = other['options']['counted_join_inputs']
    original['options']['expected_counted_join_sha256'] = other['options']['expected_counted_join_sha256']
    with pytest.raises(ValueError):
        _counted_companion_prepare(original)


def test_counted_companion_requires_an_original_source_only_example_not_a_labelled_relational_example(
        counted_companion_case):
    case = deepcopy(counted_companion_case)
    labelled = make_case()
    assert labelled['source']['model_input'] == case['source']['model_input']
    case['source'] = labelled['source']
    case['options']['expected_source_example_sha256'] = sha(wire(labelled['source']))
    case['options']['source_example_inputs'] = {'join_report': labelled['join'], **labelled['options']}
    with pytest.raises(ValueError):
        _counted_companion_prepare(case)


@pytest.mark.parametrize('damage', ['source', 'source_pin', 'counted_correspondence', 'counted_pin',
    'content', 'context', 'sidecar', 'token_ids', 'producer', 'authority', 'mask'])
def test_counted_companion_resealed_output_cannot_replace_public_regeneration(
        counted_companion_case, damage):
    case = deepcopy(counted_companion_case)
    report = _counted_companion_prepare(case)
    if damage == 'source': report['source_example']['model_input']['source_text'] += 'changed'
    elif damage == 'source_pin': report['source_example_sha256'] = '0' * 64
    elif damage == 'counted_correspondence': report['counted_correspondence']['provenance_ledger'].pop()
    elif damage == 'counted_pin': report['counted_correspondence_sha256'] = '0' * 64
    elif damage == 'content': report['compact_label']['content']['tree'][0] = 'exists'
    elif damage == 'context': report['compact_label']['context']['maximum'] = True
    elif damage == 'sidecar': report['compact_label']['identity_sidecar']['node_ids'].reverse()
    elif damage == 'token_ids': report['compact_encoding']['target_ids'].pop()
    elif damage == 'producer': report['producer_pins'] = {}
    elif damage == 'authority': report['authority'][next(iter(report['authority']))] = True
    else: report['training_mask'] = 1
    with pytest.raises(ValueError):
        _counted_companion_validate(report, case)


@pytest.mark.parametrize('location', ['source', 'counted_correspondence', 'counted_report'])
def test_counted_companion_offered_foreign_producer_paths_are_not_opened(
        counted_companion_case, monkeypatch, tmp_path, location):
    case = deepcopy(counted_companion_case)
    foreign = tmp_path / 'never-read-counted-owner.py'
    target = case['source'] if location == 'source' else case['counted_join']
    if location == 'counted_report': target = target['counted_frame_report']
    target['producer_pins'][str(foreign)] = '0' * 64
    if location == 'source': case['options']['expected_source_example_sha256'] = sha(wire(case['source']))
    else: case['options']['expected_counted_join_sha256'] = sha(wire(case['counted_join']))
    read = Path.read_bytes
    def guarded(path):
        assert path != foreign, 'offered foreign producer path was opened'
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded)
    with pytest.raises(ValueError):
        _counted_companion_prepare(case)


@pytest.mark.parametrize('boundary', ['source', 'counted_join', 'projection', 'encoding'])
def test_counted_companion_caller_inputs_are_fenced_after_genuine_owner_callbacks(
        counted_companion_case, monkeypatch, boundary):
    case = deepcopy(counted_companion_case)
    owner, name = {'source': (examples.subject, 'validate_relational_decoder_example_v1'),
        'counted_join': (joins.subject, 'validate_source_typed_norm_join_v2'),
        'projection': (_counted_companion_owner(), 'project_counted_frame_request_v1'),
        'encoding': (_counted_companion_owner(), 'encode_counted_frame_tokens_v1')}[boundary]
    actual, seen = getattr(owner, name), []
    def changed(*args, **kwargs):
        result = actual(*args, **kwargs)
        seen.append(True)
        case['source']['model_input']['source_text'] += 'caller changed after public replay'
        return result
    monkeypatch.setattr(owner, name, changed)
    with pytest.raises(ValueError):
        _counted_companion_prepare(case)
    assert seen


@pytest.mark.parametrize('boundary', ['public_replay', 'final_wire'])
def test_counted_companion_producer_fences_cover_replay_and_complete_serialization(
        counted_companion_case, monkeypatch, boundary):
    case = deepcopy(counted_companion_case)
    watched = Path(subject.__file__)
    snapshot, ordinary_wire = subject._snapshot, subject._wire
    actual = examples.subject.validate_relational_decoder_example_v1
    armed, seen = [False], []
    def changed_snapshot(path):
        value = snapshot(path)
        if armed[0] and Path(path) == watched:
            seen.append(True)
            return ('0' * 64, value[1])
        return value
    def replay(*args, **kwargs):
        value = actual(*args, **kwargs)
        if boundary == 'public_replay': armed[0] = True
        return value
    def serialize(value, *args, **kwargs):
        result = ordinary_wire(value, *args, **kwargs)
        if boundary == 'final_wire' and type(value) is dict and value.get('schema') == 'legal-counted-compact-decoder-example/v1':
            armed[0] = True
        return result
    monkeypatch.setattr(subject, '_snapshot', changed_snapshot)
    monkeypatch.setattr(subject, '_wire', serialize)
    monkeypatch.setattr(examples.subject, 'validate_relational_decoder_example_v1', replay)
    with pytest.raises(ValueError):
        _counted_companion_prepare(case)
    assert seen


def test_counted_companion_validator_fences_offered_report_during_full_regeneration(
        counted_companion_case, monkeypatch):
    case = deepcopy(counted_companion_case)
    offered = _counted_companion_prepare(case)
    actual = subject.prepare_counted_compact_decoder_example_v1
    def regenerate(*args, **kwargs):
        result = actual(*args, **kwargs)
        offered['compact_encoding']['target_ids'].pop()
        return result
    monkeypatch.setattr(subject, 'prepare_counted_compact_decoder_example_v1', regenerate)
    with pytest.raises(ValueError):
        _counted_companion_validate(offered, case)


def test_counted_companion_originals_and_returned_labels_are_detached(counted_companion_case):
    case = deepcopy(counted_companion_case)
    before = deepcopy(case)
    report = _counted_companion_prepare(case)
    preserved = deepcopy(report)
    report['compact_label']['content']['tree'][0] = 'changed'
    report['source_example']['model_input']['context']['text'] = 'changed'
    assert case == before
    assert _counted_companion_prepare(case) == preserved


@pytest.mark.parametrize('owner_kind', ['source', 'counted_join'])
def test_counted_companion_operational_public_replay_errors_propagate_unchanged(
        counted_companion_case, monkeypatch, owner_kind):
    owner, name = ((examples.subject, 'validate_relational_decoder_example_v1') if owner_kind == 'source'
                   else (joins.subject, 'validate_source_typed_norm_join_v2'))
    failure = OSError('authored operational dependency is unavailable')
    def unavailable(*args, **kwargs):raise failure
    monkeypatch.setattr(owner, name, unavailable)
    with pytest.raises(OSError) as raised:
        _counted_companion_prepare(deepcopy(counted_companion_case))
    assert raised.value is failure


def test_counted_companion_complete_input_bound_refuses_before_owner_discovery(
        counted_companion_case, monkeypatch):
    monkeypatch.setattr(subject, 'MAX_INPUT_BYTES', 1)
    monkeypatch.setattr(subject, '_counted_example_owners', lambda: pytest.fail('owner discovery after complete input overflow'))
    with pytest.raises(ValueError):
        _counted_companion_prepare(deepcopy(counted_companion_case))


@pytest.mark.parametrize('returned_value', ['expression_commitment', 'truncated_token_ids'])
def test_counted_companion_refuses_inconsistent_genuine_public_projection_or_encoding_returns(
        counted_companion_case, monkeypatch, returned_value):
    """Corrupt only one returned field after each genuine owner has succeeded."""
    counted = _counted_companion_owner()
    name = ('project_counted_frame_request_v1' if returned_value == 'expression_commitment'
            else 'encode_counted_frame_tokens_v1')
    actual, observed = getattr(counted, name), []
    def changed(*args, **kwargs):
        result = actual(*args, **kwargs)
        observed.append(True)
        if returned_value == 'expression_commitment':
            result['original_expression_sha256'] = '0' * 64
        else:
            result['target_ids'].pop()
        return result
    monkeypatch.setattr(counted, name, changed)
    with pytest.raises(ValueError):
        _counted_companion_prepare(deepcopy(counted_companion_case))
    assert observed == [True]

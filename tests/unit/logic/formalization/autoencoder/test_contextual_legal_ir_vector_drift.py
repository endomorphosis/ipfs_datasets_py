"""Pure binary32 drift controls; no Torch, retained inputs or model execution."""
from copy import deepcopy
import hashlib
import math

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as subject


def row(identifier, original, successor):
    return dict(id=identifier, original=list(original), successor=list(successor))


def test_source_vector_drift_identity_preserves_order_and_unqualified_scope():
    assert 'compare_source_vector_drift_v1' in subject.__all__
    rows = [row('z', [1., 0.], [1., 0.]), row('a', [3., 4.], [3., 4.])]
    report = subject.compare_source_vector_drift_v1(rows, dimension=2)
    assert report['schema'] == 'legal-ir-raw-source-vector-drift/v1'
    assert report['dimension'] == 2 and [item['id'] for item in report['rows']] == ['z', 'a']
    assert report['counts'] == dict(row_count=2, scalar_pairs=4, exact_bitwise_rows=2,
        bitwise_differing_coordinates=0, numerically_differing_coordinates=0)
    assert report['input_dtype'] == 'binary32_exact'
    assert report['arithmetic_dtype'] == 'python_binary64_fsum_hypot'
    assert report['ulp_policy'] == 'signed-magnitude numerical rank with signed zeros coalesced'
    assert report['acceptance_tolerance'] is None
    assert report['preprocessing_applied'] is report['model_restored'] is report['conditioning_or_head_compatibility_qualified'] is False
    assert all(report[key] is False for key in subject._FALSE)
    for item, norm in zip(report['rows'], [1., 5.]):
        assert item['bitwise_equal'] is True
        assert item['original_l2_norm'] == item['successor_l2_norm'] == norm
        assert item['max_absolute_error'] == item['l1_distance'] == item['l2_distance'] == 0.
        assert item['relative_l2_distance'] == item['cosine_distance'] == 0.
        assert item['relative_l2_undefined_reason'] is item['cosine_undefined_reason'] is None
        assert item['max_ulp_distance'] == item['mean_ulp_distance'] == 0
        assert 'original' not in item and 'successor' not in item
    assert report['rows'][0]['original_f32_be_sha256'] == hashlib.sha256(bytes.fromhex('3f80000000000000')).hexdigest()


def test_source_vector_drift_orthogonal_and_opposed_have_known_distances():
    report = subject.compare_source_vector_drift_v1([
        row('orthogonal', [1., 0.], [0., 1.]), row('opposed', [1., 0.], [-1., 0.])], dimension=2)
    orthogonal, opposed = report['rows']
    assert orthogonal['dot_product'] == orthogonal['cosine_similarity'] == 0.
    assert orthogonal['l2_distance'] == pytest.approx(math.sqrt(2.))
    assert orthogonal['cosine_distance'] == 1.
    assert opposed['dot_product'] == opposed['cosine_similarity'] == -1.
    assert opposed['l1_distance'] == opposed['l2_distance'] == opposed['cosine_distance'] == 2.
    assert not any(item['cosine_roundoff_clipped'] or item['cosine_distance_roundoff_clipped'] for item in report['rows'])


def test_source_vector_drift_preserves_norm_drift_and_relative_direction():
    report = subject.compare_source_vector_drift_v1([
        row('down', [2., 0.], [1., 0.]), row('up', [1., 0.], [2., 0.])], dimension=2)
    down, up = report['rows']
    assert down['original_l2_norm'] == up['successor_l2_norm'] == 2.
    assert down['successor_l2_norm'] == up['original_l2_norm'] == 1.
    assert down['relative_l2_distance'] == .5 and up['relative_l2_distance'] == 1.
    assert all(item['l2_distance'] == item['cosine_similarity'] == 1. and item['cosine_distance'] == 0. for item in report['rows'])


def test_source_vector_drift_zero_norm_policies_are_explicit():
    report = subject.compare_source_vector_drift_v1([
        row('both', [0., 0.], [0., 0.]), row('old-zero', [0., 0.], [3., 4.]),
        row('new-zero', [3., 4.], [0., 0.])], dimension=2)
    for item, reason in zip(report['rows'], ['both_zero_norms', 'original_zero_norm', 'successor_zero_norm']):
        assert item['cosine_similarity'] is item['cosine_distance'] is None
        assert item['cosine_undefined_reason'] == reason
        assert item['cosine_roundoff_clipped'] is item['cosine_distance_roundoff_clipped'] is False
    both, old, new = report['rows']
    for item in (both, old):
        assert item['relative_l2_distance'] is None and item['relative_l2_undefined_reason'] == 'original_zero_norm'
    assert new['relative_l2_distance'] == 1. and new['relative_l2_undefined_reason'] is None
    assert old['l2_distance'] == new['l2_distance'] == 5.
    assert old['l1_distance'] == new['l1_distance'] == 7.


def test_source_vector_drift_signed_zero_has_distinct_bits_but_zero_numerical_ulp():
    report = subject.compare_source_vector_drift_v1([row('signed-zero', [0.], [-0.])], dimension=1)
    item = report['rows'][0]
    assert item['original_f32_be_sha256'] == hashlib.sha256(bytes.fromhex('00000000')).hexdigest()
    assert item['successor_f32_be_sha256'] == hashlib.sha256(bytes.fromhex('80000000')).hexdigest()
    assert item['bitwise_equal'] is False
    assert item['bitwise_differing_coordinates'] == 1 and item['numerically_differing_coordinates'] == 0
    assert item['max_absolute_error'] == item['l2_distance'] == item['max_ulp_distance'] == item['mean_ulp_distance'] == 0
    assert report['counts']['exact_bitwise_rows'] == 0


def test_source_vector_drift_adjacent_positive_binary32_is_one_ulp():
    difference = 2.**-23
    item = subject.compare_source_vector_drift_v1([row('adjacent', [1.], [1.+difference])], dimension=1)['rows'][0]
    assert item['max_absolute_error'] == item['l1_distance'] == item['l2_distance'] == difference
    assert item['relative_l2_distance'] == difference
    assert item['max_ulp_distance'] == item['mean_ulp_distance'] == 1
    assert item['cosine_similarity'] == 1. and item['cosine_distance'] == 0.
    near = subject.compare_source_vector_drift_v1(
        [row('near-parallel', [1., 0.], [1., 2.**-30])], dimension=2)['rows'][0]
    assert near['cosine_similarity'] == 1.
    assert near['cosine_distance'] == 2.**-61 and near['cosine_distance'] > 0.


def test_source_vector_drift_negative_adjacent_and_subnormal_crossing_use_numerical_ranks():
    tiny = 2.**-149
    rows = [row('negative-adjacent', [-1.], [-1.+2.**-24]),
        row('cross-zero', [-tiny], [tiny]), row('positive-subnormal', [tiny], [2*tiny])]
    negative, cross, positive = subject.compare_source_vector_drift_v1(rows, dimension=1)['rows']
    assert negative['max_ulp_distance'] == negative['mean_ulp_distance'] == 1
    assert negative['l2_distance'] == 2.**-24
    assert cross['max_ulp_distance'] == cross['mean_ulp_distance'] == 2
    assert cross['l2_distance'] == 2*tiny and cross['cosine_similarity'] == -1. and cross['cosine_distance'] == 2.
    assert positive['max_ulp_distance'] == 1 and positive['l2_distance'] == tiny


def test_source_vector_drift_largest_finite_binary32_stays_finite_in_binary64_metrics():
    largest = float.fromhex('0x1.fffffep+127')
    item = subject.compare_source_vector_drift_v1([row('large', [largest], [-largest])], dimension=1)['rows'][0]
    assert item['original_l2_norm'] == item['successor_l2_norm'] == largest
    assert item['l1_distance'] == item['l2_distance'] == 2*largest
    assert item['relative_l2_distance'] == item['cosine_distance'] == 2.
    assert item['cosine_similarity'] == -1.
    assert all(math.isfinite(item[key]) for key in ('dot_product', 'l1_distance', 'l2_distance', 'original_l2_norm', 'successor_l2_norm'))


def test_source_vector_drift_fsum_preserves_tiny_dot_after_cancellation():
    large = 2.**50
    item = subject.compare_source_vector_drift_v1([row('cancellation', [large, 1., large], [large, 1., -large])], dimension=3)['rows'][0]
    assert item['dot_product'] == 1.
    assert item['cosine_similarity'] > 0.
    assert item['cosine_similarity'] == pytest.approx(2.**-101, rel=2e-15, abs=0.)
    assert item['cosine_distance'] == pytest.approx(1., rel=2e-15, abs=0.)


def test_source_vector_drift_detaches_results_and_never_calls_numerical_model_facades(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('pure drift invoked a model/owner facade')
    for name in ('_owners', 'restore_contextual_legal_model', 'infer_contextual_legal_model'):
        monkeypatch.setattr(subject, name, forbidden)
    shared = [1., 0.]
    rows = [dict(id='one', original=shared, successor=shared), dict(id='two', original=shared, successor=shared)]
    saved = deepcopy(rows)
    report = subject.compare_source_vector_drift_v1(rows, dimension=2)
    assert rows == saved and rows[0]['original'] is rows[1]['successor'] is shared
    report['rows'][0]['id'] = 'changed'; report['counts']['row_count'] = 99
    again = subject.compare_source_vector_drift_v1(rows, dimension=2)
    assert rows == saved and again['rows'][0]['id'] == 'one' and again['counts']['row_count'] == 2


def test_source_vector_drift_dimension_requires_bounded_exact_integer():
    rows = [row('one', [1.], [1.])]
    for dimension in (True, False, 0, -1, 4097, 1., '1', None):
        with pytest.raises(ValueError):
            subject.compare_source_vector_drift_v1(rows, dimension=dimension)


def test_source_vector_drift_outer_rows_require_nonempty_exact_list():
    class AliasedList(list):
        def __iter__(self): raise AssertionError('rows subclass callback invoked')
    valid = row('one', [1.], [1.])
    for rows in ([], (valid,), {'one': valid}, None, 'rows', AliasedList([valid])):
        with pytest.raises(ValueError):
            subject.compare_source_vector_drift_v1(rows, dimension=1)


def test_source_vector_drift_rows_require_closed_exact_dictionaries():
    class AliasedDict(dict):
        def __iter__(self): raise AssertionError('row subclass callback invoked')
    valid = row('one', [1.], [1.])
    for value in ({'id': 'one', 'original': [1.]}, {**valid, 'extra': False}, list(valid.items()), AliasedDict(valid)):
        with pytest.raises(ValueError):
            subject.compare_source_vector_drift_v1([value], dimension=1)


def test_source_vector_drift_id_requires_exact_bounded_nonblank_utf8_without_nul():
    class AliasedString(str):
        def encode(self, *args, **kwargs): raise AssertionError('ID subclass callback invoked')
    for identifier in ('', ' \t\n', 'bad\0id', 'x'*513, 'é'*257, '\ud800', 1, b'id', AliasedString('id')):
        with pytest.raises(ValueError):
            subject.compare_source_vector_drift_v1([row(identifier, [1.], [1.])], dimension=1)


def test_source_vector_drift_duplicate_ids_refuse_even_for_different_vectors():
    with pytest.raises(ValueError):
        subject.compare_source_vector_drift_v1([row('same', [1.], [2.]), row('same', [3.], [4.])], dimension=1)


def test_source_vector_drift_vectors_require_exact_list_and_declared_width():
    class AliasedList(list):
        def __iter__(self): raise AssertionError('vector subclass callback invoked')
    for field in ('original', 'successor'):
        for value in ((1., 0.), [], [1.], [1., 0., 0.], AliasedList([1., 0.])):
            offered = row('one', [1., 0.], [1., 0.]); offered[field] = value
            with pytest.raises(ValueError):
                subject.compare_source_vector_drift_v1([offered], dimension=2)


def test_source_vector_drift_scalars_refuse_bool_integer_and_float_subclass_callbacks():
    class AliasedFloat(float):
        def __float__(self): raise AssertionError('float subclass callback invoked')
    for field in ('original', 'successor'):
        for value in (True, False, 1, '1.0', None, AliasedFloat(1.)):
            offered = row('one', [1.], [1.]); offered[field][0] = value
            with pytest.raises(ValueError):
                subject.compare_source_vector_drift_v1([offered], dimension=1)


def test_source_vector_drift_nonfinite_overflow_and_nonbinary32_values_refuse():
    for field in ('original', 'successor'):
        for value in (float('nan'), float('inf'), -float('inf'), 2.**128, .1, 2.**-150):
            offered = row('one', [1.], [1.]); offered[field][0] = value
            with pytest.raises(ValueError):
                subject.compare_source_vector_drift_v1([offered], dimension=1)


def test_source_vector_drift_row_and_combined_scalar_caps_precede_vector_traversal(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('oversized input traversed scalar values')
    monkeypatch.setattr(subject.math, 'isfinite', forbidden)
    with pytest.raises(ValueError):
        subject.compare_source_vector_drift_v1([row(str(index), [1.], [1.]) for index in range(4097)], dimension=1)
    shared = [0.]*4096
    with pytest.raises(ValueError, match='scalar'):
        subject.compare_source_vector_drift_v1([dict(id=str(index), original=shared, successor=shared) for index in range(129)], dimension=4096)


def test_source_vector_drift_default_dimension_and_inclusive_id_dimension_limits():
    default = [1.] + [0.]*383
    report = subject.compare_source_vector_drift_v1([row('é'*256, default, default)])
    assert report['dimension'] == 384 and report['counts']['scalar_pairs'] == 384
    assert len(report['rows'][0]['id'].encode('utf8')) == 512
    wide = [0.]*4096
    report = subject.compare_source_vector_drift_v1([row('maximum-dimension', wide, wide)], dimension=4096)
    assert report['dimension'] == report['counts']['scalar_pairs'] == 4096
    assert report['rows'][0]['bitwise_equal'] is True

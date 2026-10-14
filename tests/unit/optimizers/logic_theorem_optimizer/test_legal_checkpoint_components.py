"""Synthetic stdlib-only codec controls; no trained checkpoint or model reads."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[4] / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_checkpoint_components.py'
spec = importlib.util.spec_from_file_location('inert_checkpoint_components', SOURCE)
codec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codec)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture():
    weights = [[float(i) / 13 for i in range(32)] for _ in range(8)]
    weights[0][0] = -0.0
    cp = dict(schema='synthetic-checkpoint/v1', model_state={'layer.weight': weights},
              implementation={'source_sha256': 'a' * 64},
              user_metadata={'component': ['literal metadata', {'kind': 'component'}]})
    cp['parents'] = [dict(schema='synthetic-parent/v1', model_state=copy.deepcopy(cp['model_state']),
                          implementation=copy.deepcopy(cp['implementation']), sequence=i) for i in range(12)]
    original = raw(cp)
    identity = dict(expected_checkpoint_sha256=sha(original),
                    expected_model_state_sha256=sha(raw(cp['model_state'])),
                    expected_implementation_sha256=sha(raw(cp['implementation'])))
    return cp, original, identity


class ComponentsTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.original, self.identity = fixture()
        self.packed = codec.pack_checkpoint(self.original, **self.identity)

    def unpack(self, packed=None, **kwargs):
        p = self.packed if packed is None else packed
        return codec.unpack_checkpoint(p, expected_archive_sha256=sha(p), **(self.identity | kwargs))

    def mutate(self, change):
        value = json.loads(self.packed)
        change(value)
        return raw(value)

    def test_exact_roundtrip_dedup_determinism_and_signed_zero(self):
        self.assertEqual(self.unpack(), self.original)
        self.assertEqual(codec.pack_checkpoint(self.original, **self.identity), self.packed)
        archive = json.loads(self.packed)
        self.assertEqual(len(archive['components']), 1)
        self.assertEqual(archive['manifest']['component_references'], 13)
        self.assertLess(len(self.packed), len(self.original) // 2)
        restored = json.loads(self.unpack())
        self.assertEqual(math.copysign(1., restored['model_state']['layer.weight'][0][0]), -1.)
        self.assertEqual(restored['user_metadata'], self.cp['user_metadata'])

    def test_raw_archive_and_each_trusted_identity_must_match(self):
        with self.assertRaises(ValueError):
            codec.unpack_checkpoint(self.packed, expected_archive_sha256='f' * 64, **self.identity)
        for key in self.identity:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.unpack(**{key: 'f' * 64})
            with self.subTest(pack_key=key), self.assertRaises(ValueError):
                codec.pack_checkpoint(self.original, **(self.identity | {key: 'f' * 64}))

    def test_missing_extra_corrupt_shape_and_numeric_type_components_rejected(self):
        key = next(iter(json.loads(self.packed)['components']))
        changes = [lambda a: a['components'].clear(),
                   lambda a: a['components'].update({'f' * 64: copy.deepcopy(a['components'][key])}),
                   lambda a: a['components'][key]['data'][0].__setitem__(1, 99.),
                   lambda a: a['components'][key].update(shape=[32, 8]),
                   lambda a: a['components'][key].update(shape=[True, 32]),
                   lambda a: a['components'][key]['data'][0].__setitem__(1, True),
                   lambda a: a['components'][key].update(extra=False)]
        for i, change in enumerate(changes):
            with self.subTest(case=i), self.assertRaises(ValueError):
                self.unpack(self.mutate(change))

    def test_closed_manifest_schema_and_reference_inventory(self):
        changes = [lambda a: a.update(extra={}), lambda a: a.update(schema='other/v1'),
                   lambda a: a['manifest'].update(extra=False),
                   lambda a: a['manifest'].update(component_references=12),
                   lambda a: a['manifest'].update(component_count=True),
                   lambda a: a['manifest'].update(checkpoint_schema='changed/v1'),
                   lambda a: a['manifest'].update(checkpoint_bytes=len(self.original) - 1)]
        for i, change in enumerate(changes):
            with self.subTest(case=i), self.assertRaises(ValueError):
                self.unpack(self.mutate(change))

    def test_tokens_reject_missing_refs_unknown_kinds_duplicate_keys_and_cycles(self):
        changes = [lambda a: a.update(skeleton=['component', 'f' * 64]),
                   lambda a: a.update(skeleton=['unknown', None]),
                   lambda a: a.update(skeleton=['value', {}]),
                   lambda a: a.update(skeleton=['map', [['x', ['value', 1]], ['x', ['value', 2]]]]),
                   lambda a: a.update(skeleton=['map', [['z', ['value', 1]], ['a', ['value', 2]]]]),
                   lambda a: a.update(skeleton=['component', ['component', 'f' * 64]])]
        for i, change in enumerate(changes):
            with self.subTest(case=i), self.assertRaises(ValueError):
                self.unpack(self.mutate(change))
        cyclic = []; cyclic.append(cyclic)
        with self.assertRaises(ValueError):
            codec._bounded(cyclic)

    def test_expansion_budget_refuses_before_serializing_large_result(self):
        archive = json.loads(self.packed)
        key = next(iter(archive['components']))
        archive['skeleton'] = ['list', [['component', key] for _ in range(1000)]]
        archive['manifest']['component_references'] = 1000
        expanded = raw(archive)
        original_raw = codec._raw
        seen = []
        def bounded_raw(value):
            seen.append(len(value) if isinstance(value, list) else None)
            if isinstance(value, list) and len(value) == 1000:
                raise AssertionError('expanded result must be rejected before serialization')
            return original_raw(value)
        codec._raw = bounded_raw
        try:
            with self.assertRaisesRegex(ValueError, 'expanded list byte bound'):
                self.unpack(expanded)
        finally:
            codec._raw = original_raw
        self.assertNotIn(1000, seen)

    def test_duplicate_noncanonical_nonfinite_and_deep_input_rejected(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'{ "x": 1 }',
                      b'[' * 130 + b'0' + b']' * 130):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                codec.pack_checkpoint(value, **(self.identity | dict(expected_checkpoint_sha256=sha(value))))

    def test_integer_float_and_marker_like_metadata_remain_distinct(self):
        cp = copy.deepcopy(self.cp)
        cp['model_state']['ints'] = list(range(8))
        cp['model_state']['floats'] = [float(i) for i in range(8)]
        cp['literal'] = ['component', 'f' * 64]
        original = raw(cp)
        identity = self.identity | dict(expected_checkpoint_sha256=sha(original), expected_model_state_sha256=sha(raw(cp['model_state'])))
        packed = codec.pack_checkpoint(original, **identity)
        self.assertEqual(codec.unpack_checkpoint(packed, expected_archive_sha256=sha(packed), **identity), original)

    def test_all_bounded_sizes_and_no_model_libraries(self):
        for bad in (b'', bytearray(self.original), self.original + b' '):
            with self.subTest(bad_type=type(bad).__name__), self.assertRaises(ValueError):
                codec.pack_checkpoint(bad, **self.identity)
        old = codec.MAX_BYTES
        codec.MAX_BYTES = len(self.original) - 1
        try:
            with self.assertRaises(ValueError):
                codec.pack_checkpoint(self.original, **self.identity)
        finally:
            codec.MAX_BYTES = old
        self.assertFalse({'torch', 'numpy', 'transformers', 'sentence_transformers'} & set(sys.modules))


if __name__ == '__main__':
    unittest.main()

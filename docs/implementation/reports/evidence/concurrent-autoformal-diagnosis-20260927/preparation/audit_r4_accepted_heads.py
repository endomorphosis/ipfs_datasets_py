"""Audit retained sparse bytes with stdlib only; never train, evaluate, or replay."""
import ast
import hashlib
import json
import math
from pathlib import Path
import struct

D = Path('/home/barberb/lift_coding/.git/modules/external/ipfs_datasets/concurrent-autoformal-diagnosis-20260927')
ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
TRAIN = ROOT / 'workspace/test-logs/federal-corpus-audits/concurrent-autoformal-diagnosis-20260927/capture-r4/supervisor/lanes/training'
SOURCE = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py'
inputs = {}


def read(path, maximum=30_000_000):
    path = Path(path)
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum
    raw = path.read_bytes()
    inputs[str(path)] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return raw


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, allow_nan=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def encode(value):
    if value is None:
        return ['null']
    if type(value) is str:
        return ['str', value]
    if type(value) is float:
        assert math.isfinite(value)
        return ['float64', struct.pack('>d', value).hex()]
    if type(value) is int:
        return ['int', str(value)]
    if type(value) is dict:
        return ['dict', [[encode(k), encode(v)] for k, v in value.items()]]
    raise ValueError('unsupported retained head value')


def decode(value):
    if value == ['null']:
        return None
    assert type(value) is list and len(value) == 2
    kind, raw = value
    if kind == 'str':
        assert type(raw) is str
        return raw
    if kind == 'float64':
        result = struct.unpack('>d', bytes.fromhex(raw))[0]
        assert math.isfinite(result)
        return result
    if kind == 'int':
        return int(raw)
    if kind == 'dict':
        result = {}
        for key, item in raw:
            key = decode(key)
            assert key not in result
            result[key] = decode(item)
        return result
    raise ValueError('unsupported retained typed head value')


def flatten(value, prefix=()):
    if isinstance(value, dict):
        return {path: number for key, child in value.items()
                for path, number in flatten(child, prefix + (key,)).items()}
    assert type(value) in (int, float) and math.isfinite(value)
    return {prefix: float(value)}


receipt_path = TRAIN / 'native/receipt.json'
receipt = json.loads(read(receipt_path, 4_000_000))
assert receipt['execution_mode'] == 'native_training' and receipt['optimizer_accepted_epochs'] == 1
assert receipt['shared_targets_verified'] and receipt['shared_target_count'] == 5
assert receipt['shared_target_status_counts'] == {'ready': 5}
assert receipt['admitted'] is False and receipt['promotion_performed'] is False
source = read(SOURCE, 2_000_000)
assert inputs[str(SOURCE)]['sha256'] == receipt['tree_file_sha256']['autoencoder']
assign = next(node for node in ast.parse(source).body if isinstance(node, ast.AnnAssign)
    and isinstance(node.target, ast.Name) and node.target.id == 'LEGAL_IR_TRAINABLE_HEAD_FIELDS')
registry = ast.literal_eval(assign.value)
base_descriptor = receipt['base_checkpoint']
base = json.loads(read(base_descriptor['path']))
assert inputs[base_descriptor['path']] == {key: base_descriptor[key] for key in ('sha256', 'bytes')}
assert base_descriptor['sha256'] == '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
manifest_descriptor = receipt['candidate']
manifest = json.loads(read(manifest_descriptor['path'], 100_000))
assert inputs[manifest_descriptor['path']] == {key: manifest_descriptor[key] for key in ('sha256', 'bytes')}
segments = receipt['sparse_patch_segments']
assert len(segments) == 1
segment = segments[0]
assert manifest['patches'] == [{key: segment[key] for key in ('sha256', 'bytes')}]
envelope = json.loads(read(segment['path'], 10_000_000))
assert inputs[segment['path']] == {key: segment[key] for key in ('sha256', 'bytes')}
payload = envelope['payload']
assert canonical_digest(payload) == envelope['payload_sha256']
assert payload['base_state_identity'] == receipt['base_state_identity']['digest']
assert payload['result_state_identity'] == manifest['state_identity']
assert payload['components'] == []  # This retained patch uses exclusively row postimages.
epoch = receipt['training_report']['epoch_reports'][0]
assert epoch['accepted'] and epoch['selected_update'] == 'family_logits'
assert decode(payload['provenance'])['commit_label'] == 'projection-commit:1:family_logits'
norms = epoch['trainable_legal_ir_head_norms']
assert norms['finite'] and norms['trainable_head_families'] == registry
squares, counts, rows_by_field = {}, {}, {}
seen = set()
for row in payload['rows']:
    field, key = row['component'], decode(row['key'])
    assert (field, key) not in seen
    seen.add((field, key))
    before_map = base.get(field, {})
    exists = key in before_map
    before = before_map[key] if exists else None
    assert exists == row['before_exists']
    assert canonical_digest([exists, encode(before) if exists else ['null']]) == row['before_sha256']
    after = decode(row['after_value'])
    if field not in registry:
        continue
    rows_by_field[field] = rows_by_field.get(field, 0) + 1
    old = flatten(before) if exists else {}
    new = flatten(after) if row['after_exists'] else {}
    for path in set(old) | set(new):
        delta = new.get(path, 0.0) - old.get(path, 0.0)
        assert math.isfinite(delta)
        if delta:
            counts[field] = counts.get(field, 0) + 1
            squares.setdefault(field, []).append(delta * delta)
actual = {field: math.sqrt(math.fsum(values)) for field, values in squares.items()}
assert counts == norms['scalar_update_counts_by_head']
assert set(actual) == set(norms['update_norms_by_head'])
assert all(math.isclose(value, norms['update_norms_by_head'][field], rel_tol=1e-9, abs_tol=1e-12)
           for field, value in actual.items())
categories = {}
for category in ('compiler_facing_legal_ir_view', 'decompiler'):
    fields = [field for field, group in registry.items() if group == category]
    committed = [field for field in fields if counts.get(field, 0) > 0 and actual.get(field, 0) > 0]
    categories[category] = {'declared_fields': fields, 'committed_nonzero_fields': committed,
        'passed': bool(committed)}
original_path = TRAIN / 'learned-head-observation.json'
original = json.loads(read(original_path, 1_000_000))
assert original['compiler_facing_update_committed'] is False
for path, binding in inputs.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == binding['sha256']
result = {'schema': 'retained-r4-category-based-accepted-head-audit/v1',
    'passed': all(item['passed'] for item in categories.values()),
    'scope': 'Independent retained-artifact audit; no training, evaluation, patch replay, or change to original smoke result.',
    'registry_source': {'path': str(SOURCE), 'sha256': inputs[str(SOURCE)]['sha256'], 'symbol': 'LEGAL_IR_TRAINABLE_HEAD_FIELDS'},
    'categories': categories, 'selected_update': epoch['selected_update'],
    'selected_line_search_attempt': epoch['line_search_attempt'], 'selected_objective_gain': epoch['objective_delta'],
    'committed_head_rows': rows_by_field, 'committed_scalar_counts': counts,
    'recomputed_update_norms': actual, 'native_reported_update_norms': norms['update_norms_by_head'],
    'verified_patch_row_before_image_count': len(payload['rows']),
    'sparse_patch_bytes': segment['bytes'], 'base_checkpoint_unchanged': True,
    'original_helper_observation': {'path': str(original_path), 'sha256': inputs[str(original_path)]['sha256'],
        'compiler_facing_update_committed': original['compiler_facing_update_committed'],
        'decompiler_update_committed': original['decompiler_update_committed'],
        'preserved_unchanged': True,
        'diagnosis': 'Helper enumerates only legal_ir_view_logits and feature_legal_ir_view_logits; it omits the already-declared compiler-facing legal_ir_view_family_logits head.'},
    'shared_target_count': 5, 'shared_target_status_counts': {'ready': 5},
    'acceptance_criteria_changed': False, 'admitted': False, 'formalized': False,
    'native_supervisor_success_inferred': False, 'inputs': inputs}
output = D / 'r4-accepted-head-audit.json'
with output.open('x') as handle:
    json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
    handle.write('\n')
print(json.dumps({'path': str(output), 'passed': result['passed'], 'counts': counts,
                  'norms': actual, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}, indent=2))

"""Pure saved-output comparison for the registered permission-retention pair.

This helper never restores a model or parses checkpoint JSON. All two-cell raw
inventories and completed-run fences must pass before reference scoring. The
references are already exposed authored engineering declarations, not a blind
or independently reviewed legal evaluation. No candidate is selected.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import struct
import sys
from types import SimpleNamespace

M = Path(__file__).resolve().parent
N2 = M.parent / 'legal-targeted-loss-20261012-01'
T = M.parent / 'legal-temporal-binding-20261012-01'
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
CELLS = ('all-parameters', 'span-heads-only')
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
COUNTS = dict(old_tune=96, fresh_tune=36, fresh_challenge=36, old_authored_eval=72, authored_dev=72, authored_eval=72, law=8)
MODALITIES = ('O', 'P', 'F')
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
N2_ANALYZER = N2 / 'analyze_targeted_results_v01.py'
N2_ANALYZER_PIN = dict(bytes=66275, sha256='4274d682da303954689bbb318750a91a49b407961f26d718104e1890a0ae4d0f')
HELPER = T / 'run_temporal_contrast_pilot.py'
HELPER_SHA = '0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'
PACKET = N2 / 'authored-reference-packet-v01.json'
EXPORT = M / 'training-export-v01.json'
REGISTRATION = M / 'registration-v01.json'
RUNNER = M / 'run_permission_retention.py'
TRAINER = M / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_permission_retention.py'
TRAINER_PIN = dict(bytes=40092, sha256='25f8d6e9ecfde1b9d28346a0f55e787abfd61b8673a0aaf1618b6c10cda82eb0')
TARGETED = M / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_targeted_loss.py'
TARGETED_PIN = dict(bytes=49658, sha256='f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b')
MODEL_PARAMETER_NAMES = (
    'byte_embedding.weight', 'token_projection.weight', 'token_projection.bias',
    'encoder.weight_ih_l0', 'encoder.weight_hh_l0', 'encoder.bias_ih_l0', 'encoder.bias_hh_l0',
    'encoder.weight_ih_l0_reverse', 'encoder.weight_hh_l0_reverse', 'encoder.bias_ih_l0_reverse', 'encoder.bias_hh_l0_reverse',
    'modality.weight', 'modality.bias', 'presence.weight', 'presence.bias', 'start.weight', 'start.bias', 'end.weight', 'end.bias',
    'latent_down.weight', 'latent_down.bias', 'latent_up.weight', 'latent_up.bias')
FACET_PARAMETER_NAMES = ('presence.weight', 'presence.bias', 'start.weight', 'start.bias', 'end.weight', 'end.bias')
SOURCE_PARENT_SHA = 'fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279'
SOURCE_MODEL_SHA = '54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb'
MAX_JSON_BYTES = 128 * 1024 * 1024
OUTPUT = None
PACKET_ALLOWED = False
PIN_OBSERVATIONS = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'}:
        raise AssertionError('Saved-result analysis forbids numerical/production imports')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
        'os.mkdir', 'os.remove', 'os.rename', 'os.replace', 'os.rmdir', 'os.unlink'}:
        raise AssertionError('Saved-result analysis forbids process/network/resource/filesystem operations')
    if event == 'open':
        path, mode, flags = args
        resolved = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        if resolved == PACKET and not PACKET_ALLOWED:
            raise AssertionError('Complete two-cell frozen-output checks required before reference access')
        write = isinstance(mode, str) and any(c in mode for c in 'wax+')
        write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write and (OUTPUT is None or resolved != OUTPUT):
            raise AssertionError('Only one exclusive owned output may be written')


sys.dont_write_bytecode = True
sys.addaudithook(audit)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pair(value):
    return {key: value[key] for key in ('bytes', 'sha256')}


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, 'Absolute canonical artifact required')
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'Symlink artifact refused')
        require(stat.S_ISREG(info.st_mode) if part == path else stat.S_ISDIR(info.st_mode), 'Ordinary artifact required')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno()); hashed = hashlib.sha256(); size = 0
        for block in iter(lambda: stream.read(1048576), b''):
            hashed.update(block); size += len(block)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after) == identity(path.lstat()), 'Artifact changed during raw hash')
    result = dict(path=str(path), bytes=size, sha256=hashed.hexdigest())
    PIN_OBSERVATIONS[str(path)] = result
    return result


def checked_pin(value, expected_path=None):
    require(type(value) is dict and set(value) == {'path', 'bytes', 'sha256'}, 'Closed raw artifact pin required')
    if expected_path is not None:
        require(value['path'] == str(expected_path), 'Exact artifact path required')
    actual = pin(Path(value['path']))
    require(actual == value, 'Frozen raw artifact drift')
    return actual


def read(path):
    path = Path(path)
    require(not ('checkpoint' in path.name and path.suffix == '.json'), 'Checkpoint JSON parsing is prohibited')
    require(str(path) in PIN_OBSERVATIONS, 'Raw artifact pin required before JSON parsing')
    expected = PIN_OBSERVATIONS[str(path)]
    require(path.stat().st_size == expected['bytes'] <= MAX_JSON_BYTES, 'Bounded raw-pinned JSON required before allocation')
    raw = path.read_bytes()
    require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
            'Parsed JSON bytes differ from previously observed raw pin')
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key'); result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON constant ' + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    def finite(item):
        if type(item) is float:
            require(math.isfinite(item), 'Finite JSON numbers required')
        elif type(item) is list:
            for child in item: finite(child)
        elif type(item) is dict:
            for child in item.values(): finite(child)
    finite(value)
    return value


def ordinary_inventory(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Ordinary result directory required')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlink in result bundle refused')
        if path.is_dir(): continue
        require(len(result) < 1024 and path.suffix == '.json', 'Bounded JSON-only result bundle required')
        result[str(path)] = pair(pin(path))
    return result


def detached(path, names, namespace):
    path = Path(path)
    require(str(path) in PIN_OBSERVATIONS, 'Raw source pin required before AST extraction')
    expected = PIN_OBSERVATIONS[str(path)]
    require(path.stat().st_size == expected['bytes'] <= 2 * 1024 * 1024, 'Bounded raw-pinned source required before AST parsing')
    raw = path.read_bytes()
    require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
            'AST source bytes differ from previously observed raw pin')
    tree = ast.parse(raw)
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    require({n.name for n in selected} == set(names), 'Exact pure saved-predicate set required')
    require(not any(getattr(n, 'decorator_list', []) for n in selected), 'Detached predicate decorators refused')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite scalar required')
    try:
        result = struct.unpack('>f', struct.pack('>f', float(value)))[0]
    except (OverflowError, struct.error):
        raise ValueError('Finite binary32 scalar required') from None
    require(math.isfinite(result), 'Finite binary32 scalar required')
    return result


def modality_bytes(logits):
    require(type(logits) is list and len(logits) == 3, 'Exactly three O,P,F logits required')
    result = bytearray()
    for value in logits:
        require(type(value) in (int, float) and math.isfinite(value), 'Finite modality scalar required')
        converted = f32(value)
        require(converted == value, 'Saved modality logits must already be binary32 values')
        result.extend(struct.pack('<f', converted))
    return bytes(result)


def modality_choice(logits, guard=1e-7):
    modality_bytes(logits)
    maximum = max(logits); choices = [i for i, value in enumerate(logits) if value == maximum]
    index = choices[0]
    ranked = sorted(logits, reverse=True)
    return dict(first_argmax=MODALITIES[index], maximum_tied=len(choices) != 1,
                within_ambiguity_guard=f32(ranked[0] - ranked[1]) <= guard,
                margin_binary32=f32(ranked[0] - ranked[1]))


def compare_modalities(before, after, rows, *, require_equal):
    require(len(before) == len(after) == len(rows), 'Complete modality occurrence coverage required')
    changes = []; before_bytes = bytearray(); after_bytes = bytearray()
    for source, left, right in zip(rows, before, after, strict=True):
        source_hash = hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(left['id'] == right['id'] == source['id'] and left['source_sha256'] == right['source_sha256'] == source_hash,
                'Exact source/ID modality alignment required')
        lb = modality_bytes(left['scores']['modality_logits']); rb = modality_bytes(right['scores']['modality_logits'])
        before_bytes.extend(lb); after_bytes.extend(rb)
        if lb != rb:
            changes.append(dict(id=source['id'], source_sha256=source_hash,
                                baseline_head=modality_choice(left['scores']['modality_logits']),
                                trained_head=modality_choice(right['scores']['modality_logits'])))
    require(not require_equal or not changes, 'Frozen shared encoder/modality changed a saved modality vector')
    return dict(rows=len(rows), binary32_scalars=3 * len(rows), exact_vector_matches=len(rows) - len(changes),
                changed_vector_count=len(changes), ordered_baseline_binary32_sha256=hashlib.sha256(before_bytes).hexdigest(),
                ordered_trained_binary32_sha256=hashlib.sha256(after_bytes).hexdigest(), changed_rows=changes,
                byte_order='little-endian IEEE754 binary32 in source order then O,P,F order',
                includes_abstained_rows=True, raw_and_joint_IR_retention_implied=False)


def modality_summary(rows, raw, selected, metadata=None):
    require(len(rows) == len(raw['occurrences']) == len(raw['inference']['rows']) == len(selected['rows']),
            'Complete source/raw/joint occurrence coverage required')
    require(metadata is None or len(metadata) == len(rows), 'Complete metadata coverage required')
    counts = {key: Counter() for key in ('head_first_argmax', 'raw_decoded', 'joint_decoded')}
    by_class = {}; row_observations = []; ties = near = 0
    for index, (source, occurrence, actual, chosen) in enumerate(zip(rows, raw['occurrences'], raw['inference']['rows'], selected['rows'], strict=True)):
        source_hash = hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(occurrence['id'] == chosen['id'] == source['id'] and occurrence['source_sha256'] == actual['source_sha256'] == source_hash,
                'Exact modality source/ID/hash joins required')
        head = modality_choice(occurrence['scores']['modality_logits']); ties += head['maximum_tied']; near += head['within_ambiguity_guard']
        observed = dict(head_first_argmax=head['first_argmax'],
                        raw_decoded=None if actual.get('canonical_ir') is None else actual['canonical_ir']['rules'][0]['modality'],
                        joint_decoded=None if chosen['result'].get('canonical_ir') is None else chosen['result']['canonical_ir']['rules'][0]['modality'])
        require(all(value in MODALITIES or value is None for value in observed.values()), 'Closed modality output required')
        reference = None if 'canonical_ir' not in source else source['canonical_ir']['rules'][0]['modality']
        if metadata is not None:
            require(metadata[index]['id'] == source['id'], 'Exact modality metadata/source ID alignment required')
        class_name = None if metadata is None else metadata[index]['class_name']
        if reference is not None:
            require(reference in MODALITIES, 'Closed reference modality required')
            for readout, value in observed.items(): counts[readout][reference + '->' + (value or 'abstained')] += 1
            if class_name is not None:
                bucket = by_class.setdefault(class_name, {key: Counter() for key in counts})
                for readout, value in observed.items(): bucket[readout][reference + '->' + (value or 'abstained')] += 1
        row_observations.append(dict(id=source['id'], source_sha256=source_hash, class_name=class_name,
                                     reference_modality=reference, head=head, observed_modalities=observed,
                                     raw_reason=actual.get('reason'), joint_reason=chosen['result'].get('reason')))
    permission = {readout: dict(reference_P_rows=sum(value for key, value in bucket.items() if key.startswith('P->')),
                               P_to_P=bucket.get('P->P', 0), P_to_O=bucket.get('P->O', 0),
                               P_to_F=bucket.get('P->F', 0), P_abstentions=bucket.get('P->abstained', 0))
                  for readout, bucket in counts.items()}
    return dict(rows=len(rows), reference_scored=all('canonical_ir' in source for source in rows),
                modality_confusions={key: dict(value) for key, value in counts.items()},
                permission_counts=permission, by_class={name: {k: dict(v) for k, v in buckets.items()} for name, buckets in by_class.items()},
                head_maximum_ties=ties, head_within_ambiguity_guard=near,
                head_scope='First O,P,F argmax of saved logits, including every abstained row; tied/ambiguous head is reported explicitly, not promoted to decoded IR',
                row_observations=row_observations)


def schedule(rows, seed=1729):
    epoch = cursor = 0; indices = []; ids = []
    for _ in range(32):
        order = list(range(len(rows))); random.Random(seed + epoch).shuffle(order)
        batch = order[cursor:cursor + 12]; indices.append(batch); ids.append([rows[i]['id'] for i in batch]); cursor += len(batch)
        if cursor == len(rows): epoch += 1; cursor = 0
    return dict(batch_indices=indices, batch_ids=ids, batch_indices_sha256=digest(indices),
                final_progress=dict(epochs_completed=epoch, row_cursor=cursor, optimizer_steps=32))


def reuse_scoring_predicates(owners):
    require(pair(pin(N2_ANALYZER)) == N2_ANALYZER_PIN, 'Exact independently qualified retained analyzer source required')
    namespace = dict(globals())
    detached(N2_ANALYZER, {'tokenize', 'strict_rule', 'gold_coordinates', 'candidate_mechanism', 'scorers'}, namespace)
    return namespace['scorers'](owners)


def validate_capture(raw, rows, model, greedy, joint, *, control='none', vectors=None):
    require(raw['schema'] == 'permission-retention-target-free-head-capture/v1'
            and raw['actual_source_forwards'] == len(rows) and raw['extra_capture_forwards'] == 0
            and raw['target_access'] is False and raw['teacher_forcing'] is False
            and raw['model_weights_unchanged'] is True and raw['original_greedy_observations_verified'] is True
            and raw['ambient_CPU_RNG_preserved'] is True and all(raw.get(k) is v for k, v in FALSE.items()),
            'Saved target-free capture scope differs')
    inference = raw['inference']
    require(inference['schema'] == 'bounded-permission-retention-span-legal-formula-inference/v1'
            and inference['checkpoint_sha256'] == model['checkpoint_sha256']
            and inference['source_parent_checkpoint_sha256'] == model['parent_base_sha256']
            and inference['source_parent_optimizer_steps'] == 400
            and inference['context_contract_sha256'] == model['context_sha256']
            and inference['initial_continuation_checkpoint_sha256'] == model['initial_continuation_checkpoint_sha256']
            and inference['model_state_sha256'] == model['model_state_sha256']
            and inference['training_policy'] == model['training_policy']
            and inference['training_policy_sha256'] == digest(model['training_policy'])
            and inference['legacy_single_source_readout_unchanged'] is True
            and inference['latent_ablation'] == control and inference['target_access'] is False
            and inference['teacher_forcing'] is False and inference['training_executed'] is False
            and all(inference.get(k) is v for k, v in FALSE.items()), 'Saved inference source/model/context differs')
    require(len(inference['rows']) == len(raw['occurrences']) == len(rows), 'Full source occurrence coverage required')
    for index, (source, occurrence, result) in enumerate(zip(rows, raw['occurrences'], inference['rows'], strict=True)):
        source_hash = hashlib.sha256(source['source_text'].encode()).hexdigest()
        vector = source['latent'] if vectors is None else vectors[index]
        require(occurrence['id'] == source['id'] and occurrence['source_sha256'] == result['source_sha256'] == source_hash
                and result['latent_sha256'] == digest(vector) and result['latent_input_enabled'] is False,
                'Source/ID/dormant latent join differs')
        require(result['teacher_forcing'] is False and result['target_access'] is False and result['training_executed'] is False
                and result['source_input_conditioned'] is True and result['sample_memory_used'] is False
                and all(result.get(k) is v for k, v in FALSE.items()), 'Saved raw row authority differs')
        joint['_validated'](source['source_text'], occurrence['scores'])
        greedy['_verify_greedy'](source['source_text'], occurrence['scores'], result)
    require(inference['decoded_count'] == sum(r['status'] == 'decoded' for r in inference['rows']), 'Saved decoded count differs')
    return inference['rows']


def analyze_panel(state, name, descriptor, rows, metadata, model, greedy, joint, scorer, saved, result_root):
    require(set(descriptor) == {'name', 'row_count', 'raw', 'joint', 'score', 'has_authored_reference'}
            and descriptor['name'] == name and descriptor['row_count'] == COUNTS[name], 'Exact panel descriptor/count required')
    prefix = 'baseline' if state == 'baseline' else 'trained'
    raw_path = result_root / (prefix + '-' + name + '-raw.json')
    joint_path = result_root / (prefix + '-' + name + '-joint.json')
    require(pair(checked_pin(descriptor['raw'], raw_path)) == saved[str(raw_path)]
            and pair(checked_pin(descriptor['joint'], joint_path)) == saved[str(joint_path)], 'Panel is outside frozen bundle')
    raw, selected = read(raw_path), read(joint_path)
    raw_rows = validate_capture(raw, rows, model, greedy, joint)
    require(selected['schema'] == 'permission-retention-joint-panel/v1'
            and selected['top_k'] == 8 and selected['max_search_nodes'] == 50000
            and selected['learned_presence_and_modality_fixed'] is True and len(selected['rows']) == len(rows)
            and all(selected.get(k) is v for k, v in FALSE.items()), 'Saved unchanged joint policy differs')
    for source, occurrence, chosen in zip(rows, raw['occurrences'], selected['rows'], strict=True):
        require(chosen['id'] == source['id']
                and joint['select_joint_spans'](source['source_text'], occurrence['scores'], top_k=8, max_search_nodes=50000) == chosen['result'],
                'Complete saved-logit joint replay differs')
    modalities = modality_summary(rows, raw, selected, metadata)
    if name == 'law':
        require(descriptor['score'] is None and descriptor['has_authored_reference'] is False and metadata is None,
                'Unreviewed law must remain unscored')
        require(modalities['reference_scored'] is False, 'Unreviewed law must have no reference modality')
        return dict(state=state, panel=name, rows=len(rows), raw_exact_IR=None, joint_exact_IR=None,
                    raw_decoded=sum(r['status'] == 'decoded' for r in raw_rows),
                    joint_selected=sum(r['result']['status'] == 'selected' for r in selected['rows']),
                    reference_authority='previously_exposed_unreviewed_law_without_targets', semantic_accuracy=None,
                    modalities=modalities), {}, raw, selected
    recomputed = scorer['score_panel'](rows, metadata, raw, selected['rows'])
    if name == 'authored_eval':
        require(descriptor['score'] is None and descriptor['has_authored_reference'] is False,
                'Child must retain source-only authored_eval despite prior exposure')
    else:
        require(descriptor['score'] is not None and descriptor['has_authored_reference'] is True,
                'Exposed child score required for this panel')
        score_path = result_root / (prefix + '-' + name + '-score.json')
        require(pair(checked_pin(descriptor['score'], score_path)) == saved[str(score_path)] and read(score_path) == recomputed,
                'Saved authored score differs from pure recomputation')
    compact = {r['id']: deepcopy(r) for r in recomputed['rows']}
    for item in modalities['row_observations']:
        compact[item['id']]['observed_modalities'] = item['observed_modalities']
        compact[item['id']]['reference_modality'] = item['reference_modality']
    return dict(state=state, panel=name, rows=len(rows), raw_exact_IR=recomputed['raw_exact_ir'],
                joint_exact_IR=recomputed['joint_exact_ir'], raw_exact_rate=recomputed['raw_exact_ir'] / len(rows),
                joint_exact_rate=recomputed['joint_exact_ir'] / len(rows), raw_abstentions=recomputed['raw_abstentions'],
                joint_abstentions=sum(r['result']['status'] != 'selected' for r in selected['rows']),
                modality_exact=recomputed['modality_exact'], joint_modality_exact=recomputed['joint_modality_exact'],
                role_exact_counts=recomputed['role_exact_counts'], joint_role_exact_counts=recomputed['joint_role_exact_counts'],
                temporal_presence_correct=recomputed['temporal_presence_correct'],
                temporal_false_positives=recomputed['temporal_false_positives'], temporal_false_negatives=recomputed['temporal_false_negatives'],
                classes=recomputed['classes'], pairwise_consistency=recomputed['pairwise_consistency'], modalities=modalities,
                reference_authority='previously_exposed_authored_shared_template_engineering_evaluation',
                semantic_accuracy=None, pure_recomputed_score_sha256=digest(recomputed)), compact, raw, selected


def validate_modality_receipt(receipt, cell, baseline, trained, populations):
    require(set(baseline) == set(trained) == set(populations) == set(PANELS)
            and all(len(populations[name]) == COUNTS[name] for name in PANELS)
            and sum(len(populations[name]) for name in PANELS) == 392,
            'Exact seven-panel392 source coverage required before modality receipt replay')
    require(receipt['schema'] == 'permission-retention-modality-score-comparison/v1' and receipt['cell'] == cell
            and receipt['total_source_rows'] == 392 and receipt['exact_modal_score_retention_required'] is (cell['id'] == 'span-heads-only')
            and receipt['full_IR_retention_implied'] is False and receipt['semantic_accuracy'] is None
            and all(receipt.get(k) is v for k, v in FALSE.items()), 'Saved modality-retention receipt scope differs')
    expected_panels = []; independent = []; total = 0
    for name in PANELS:
        before, after = baseline[name]['occurrences'], trained[name]['occurrences']; rows = []
        observation = compare_modalities(before, after, populations[name], require_equal=cell['id'] == 'span-heads-only')
        for source, left, right in zip(populations[name], before, after, strict=True):
            lb = modality_bytes(left['scores']['modality_logits']); rb = modality_bytes(right['scores']['modality_logits'])
            rows.append(dict(id=source['id'], source_sha256=left['source_sha256'], parent_f32_sha256=hashlib.sha256(lb).hexdigest(),
                             trained_f32_sha256=hashlib.sha256(rb).hexdigest(), bit_equal=lb == rb))
        equal = sum(r['bit_equal'] for r in rows); total += equal
        expected_panels.append(dict(name=name, rows=rows, equal_count=equal, count=len(rows)))
        independent.append(dict(panel=name, **observation))
    require(receipt['panels'] == expected_panels and receipt['bit_equal_count'] == total,
            'Saved modality receipt differs from independent complete source score replay')
    return dict(cell=cell, total_source_rows=392, binary32_scalars=1176, bit_equal_count=total,
                exact_modal_score_retention_required=cell['id'] == 'span-heads-only', panels=independent,
                full_IR_retention_implied=False, saved_receipt_independently_recomputed=True)


def training_predicates(trainer_pin):
    require(pair(pin(TARGETED)) == TARGETED_PIN, 'Exact retained objective implementation required')
    require(pair(checked_pin(trainer_pin, TRAINER)) == TRAINER_PIN, 'Exact independently authored permission trainer source required')
    common = dict(_require=require, _raw=canonical, checkpoint_digest=digest, copy=SimpleNamespace(deepcopy=deepcopy),
                  hashlib=hashlib, json=json, math=math, struct=struct, SPAN_FIELDS=FIELDS, MAX_SOURCE_TOKENS=128,
                  MAX_NEW_STEPS=32, MAX_SECONDS=32, POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
                  LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
                  span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z')))
    objective = detached(TARGETED, {'_policy', '_validate_policy', '_f32', '_span_coordinates', '_actor_domain',
                                 '_validate_objective_diagnostics', '_objective_trace_summary'}, dict(common))
    own = dict(common, targeted=SimpleNamespace(**{name: objective[name] for name in ('_policy', '_f32')}),
               MODEL_PARAMETER_NAMES=MODEL_PARAMETER_NAMES, FACET_PARAMETER_NAMES=FACET_PARAMETER_NAMES,
               POLICY_SCHEMA='bounded-source-span-permission-retention-policy/v1')
    detached(TRAINER, {'_partition', '_policy', '_validate_policy', '_modal_rows', '_freeze_entry', '_freeze_summary'}, own)
    retained = dict(globals(), targeted_pure=lambda: objective)
    detached(N2_ANALYZER, {'tokenize', 'strict_rule', 'gold_coordinates', 'validate_objective_trace'}, retained)
    return own, retained['validate_objective_trace']


def validate_training(summary, report, plan, rows, checkpoint_pin, own, objective_validator):
    require(report['schema'] == 'bounded-permission-retention-span-legal-formula-training/v1'
            and all(report.get(k) is v for k, v in FALSE.items()), 'New unqualified authoritative training report required')
    require(type(report['optimizer_steps']) is int and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
            and report['training_executed'] is True and report['stopped_reason'] == 'step_limit', 'Complete32 returned updates required')
    require(report['checkpoint_sha256'] == checkpoint_pin['sha256']
            and report['source_parent_checkpoint_sha256'] == SOURCE_PARENT_SHA
            and report['source_parent_model_state_sha256'] == SOURCE_MODEL_SHA
            and report['initial_model_state_sha256'] == report['training_call_initial_model_state_sha256'] == SOURCE_MODEL_SHA,
            'Opaque checkpoint/common-parent/current-call model bindings differ')
    require(report['previous_permission_checkpoint_sha256'] == summary['initial_checkpoint_sha256']
            and report['initial_continuation_checkpoint_sha256'] == summary['initial_continuation_checkpoint_sha256'],
            'Initial complete outer and immutable warm child bindings differ')
    for key in ('initial_checkpoint_sha256', 'final_model_state_sha256', 'frozen_parameters_sha256_initial', 'frozen_parameters_sha256_final'):
        require(type(report[key]) is str and re.fullmatch(r'[0-9a-f]{64}', report[key]), 'Reported opaque fingerprint format differs')
    policy = own['_policy'](plan['cell']['id']); partition = policy['parameter_partition']
    require(report['training_policy'] == policy and report['training_policy_sha256'] == digest(policy)
            and report['parameter_partition'] == summary['parameter_partition'] == partition
            and summary['initial_model_state_sha256'] == report['initial_model_state_sha256']
            and summary['final_model_state_sha256'] == report['final_model_state_sha256'], 'Exact parameter/objective policy or state summary differs')
    prepared = schedule(rows)
    require(summary['prepared_schedule'] == prepared, 'Same matched index schedule required')
    trace = report['batch_trace']; initial = dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
    require(trace['schema'] == 'completed-curriculum-batch-trace/v1'
            and trace['training_count'] == 168 and trace['completed_updates'] == 32
            and trace['training_manifest_sha256'] == digest(rows) and trace['batch_size'] == 12
            and trace['batch_order_seed'] == 1729 and trace['batch_order_seed_origin'] == 'explicit'
            and trace['scope'] == 'indices_and_IDs_used_by_this_trainer_recorded_after_returned_optimizer_step_and_finite_guards'
            and trace['independent_runtime_trace'] is False and trace['unreturned_partial_updates_attested'] is False
            and trace['initial_progress'] == initial and trace['final_progress'] == prepared['final_progress'],
            'Completed update trace authority/population/order/progress differs')
    batches = trace['batches']; progress = dict(initial)
    require(len(batches) == len(report['batch_losses']) == 32, 'Exactly32 completed batch losses required')
    for step, (entry, indices, ids, loss) in enumerate(zip(batches, prepared['batch_indices'], prepared['batch_ids'], report['batch_losses'], strict=True), 1):
        require(set(entry) == {'schema', 'indices', 'ids', 'pre_progress', 'post_progress', 'optimizer_step', 'loss', 'gradient_norm_before_clip'}
                and entry['schema'] == 'completed-curriculum-batch/v1' and entry['indices'] == indices and entry['ids'] == ids
                and entry['pre_progress'] == progress and type(entry['optimizer_step']) is int and entry['optimizer_step'] == step
                and type(loss) in (int, float) and math.isfinite(loss) and loss >= 0 and entry['loss'] == loss
                and type(entry['gradient_norm_before_clip']) in (int, float) and math.isfinite(entry['gradient_norm_before_clip'])
                and entry['gradient_norm_before_clip'] >= 0, 'Completed actual batch chain differs')
        progress['optimizer_steps'] += 1; progress['row_cursor'] += len(indices)
        if progress['row_cursor'] == 168: progress['epochs_completed'] += 1; progress['row_cursor'] = 0
        require(entry['post_progress'] == progress, 'Actual post-update transition differs')
    require(progress == prepared['final_progress'] and trace['indices_sha256'] == digest(prepared['batch_indices'])
            and trace['ids_sha256'] == digest(prepared['batch_ids']) and trace['batches_sha256'] == digest(batches)
            and report['gradient_norm_max'] == max(b['gradient_norm_before_clip'] for b in batches), 'Completed trace/hash/gradient summary differs')
    objective = objective_validator(report, rows, policy['objective_policy'], batches)
    freeze = report['freeze_trace']
    require(freeze == own['_freeze_summary'](freeze['batches'], batches, partition), 'Closed freeze-trace summary differs')
    previous = report['frozen_parameters_sha256_initial']; occurrence_count = 0
    for entry, batch in zip(freeze['batches'], batches, strict=True):
        records = [rows[index] for index in batch['indices']]
        expected = own['_freeze_entry'](batch['optimizer_step'], batch['indices'], records, partition,
            entry['frozen_parameters_sha256_before'], entry['frozen_parameters_sha256_after'], entry['changed_parameter_names'],
            [r['modality_logits'] for r in entry['modality_before']], [r['modality_logits'] for r in entry['modality_after']])
        require(expected == entry and entry['frozen_parameters_sha256_before'] == previous,
                'Completed freeze/source/modal/gradient/parameter trace differs')
        previous = entry['frozen_parameters_sha256_after']; occurrence_count += len(records)
    require(previous == report['frozen_parameters_sha256_final'] == report['frozen_parameters_sha256_initial']
            and occurrence_count == 384, 'Frozen-state endpoint/384-occurrence chain differs')
    if plan['cell']['id'] == 'all-parameters':
        require(previous == digest({}), 'Empty frozen subset must hash the exact empty parameter dictionary')
    changed = report['changed_parameter_names']
    require(type(changed) is list and len(changed) == len(set(changed))
            and set(changed) <= set(partition['trainable_parameter_names']) and not any(name.startswith('latent_') for name in changed),
            'Changed parameter names violate partition or dormant latent scope')
    tuning = report['tuning']
    require(type(tuning['rows_evaluated']) is int and 0 <= tuning['rows_evaluated'] <= 96
            and tuning['complete'] is (tuning['rows_evaluated'] == 96) and tuning['teacher_forcing'] is True
            and tuning['used_for_fit_or_selection'] is False and tuning['objective_policy_sha256'] == digest(policy['objective_policy'])
            and (tuning['objective_loss'] is None if tuning['rows_evaluated'] == 0 else type(tuning['objective_loss']) in (int, float)
                 and math.isfinite(tuning['objective_loss']) and tuning['objective_loss'] >= 0), 'Exposed tuning diagnostic differs')
    return dict(policy=policy, policy_sha256=digest(policy), parameter_partition=partition,
                recorded_completed_updates=32, trace_sha256=digest(trace), final_progress=progress,
                objective_trace=objective, freeze_trace_sha256=digest(freeze), freeze_training_row_occurrences=384,
                initial_model_state_sha256=report['initial_model_state_sha256'], final_model_state_sha256=report['final_model_state_sha256'],
                frozen_parameters_sha256=previous, frozen_tensor_custody_independently_attested=False,
                checkpoint_opaque_raw_pin=checkpoint_pin, checkpoint_JSON_parsed=False, changed_parameter_names_reported=changed,
                tuning_objective_loss=tuning['objective_loss'], tuning_rows=tuning['rows_evaluated'])


def expected_cell(identifier):
    require(identifier in CELLS, 'Closed parameter-policy cell required')
    return dict(id=identifier, trainable_parameter_policy=identifier, actor_ranking_enabled=False,
                presence_ce_weight=1, modality_loss_weight=2)


def expected_result_paths(root, first):
    names = {'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json', 'summary.json', 'trained-modality-retention.json'}
    for stage in ('initial', 'trained'):
        names.add(stage + '-parity.json')
        names.update(stage + '-parity-' + control + '.json' for control in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    for state in (('baseline', 'trained') if first else ('trained',)):
        for panel in PANELS:
            names.update(state + '-' + panel + '-' + kind + '.json' for kind in ('raw', 'joint'))
            if panel not in ('authored_eval', 'law'): names.add(state + '-' + panel + '-score.json')
    return {str(root / name) for name in names}


def model_binding(summary, plan, report, policy, *, initial):
    return dict(checkpoint_sha256=summary['initial_checkpoint_sha256'] if initial else report['checkpoint_sha256'],
                model_state_sha256=SOURCE_MODEL_SHA if initial else report['final_model_state_sha256'],
                initial_continuation_checkpoint_sha256=summary['initial_continuation_checkpoint_sha256'],
                parent_base_sha256=SOURCE_PARENT_SHA, context_sha256=digest(plan['context_contract']), training_policy=policy)


def validate_parity(info, rows, greedy, joint, saved):
    count = 0
    for stage, initial in (('initial', True), ('trained', False)):
        summary, report, plan, root = info['summary'], info['report'], info['plan'], info['result_root']
        descriptor = checked_pin(summary[stage + '_parity'], root / (stage + '-parity.json'))
        require(pair(descriptor) == saved[descriptor['path']], 'Parity is outside frozen bundle')
        parity = read(Path(descriptor['path']))
        require(parity['schema'] == 'source-only-dormant384-placeholder-parity/v1' and parity['passed'] is True
                and parity['source_count'] == 2 and parity['score_and_greedy_decisions_bit_equal'] is True
                and parity['genuine_latent_semantics_tested'] is False and parity['actual_encoder_calls'] == 0
                and all(parity.get(k) is v for k, v in FALSE.items()), 'Dormant placeholder parity scope differs')
        require([c['name'] for c in parity['controls']] == ['zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'],
                'All four placeholder controls required')
        projection = None
        for control in parity['controls']:
            name = control['name']; expected = {'zeros': 'none', 'alternate_placeholders': 'none', 'disabled': 'disabled', 'rotated_placeholders': 'rotate'}[name]
            require(control['control'] == expected, 'Closed dormant control mapping required')
            descriptor = checked_pin(control['report'], root / (stage + '-parity-' + name + '.json'))
            require(pair(descriptor) == saved[descriptor['path']], 'Parity capture is outside frozen bundle')
            raw = read(Path(descriptor['path']))
            vectors = [[0.] * 384 for _ in range(2)] if name == 'zeros' else [[.25 if i == 0 else -.25] * 384 for i in range(2)]
            if name == 'rotated_placeholders': vectors = vectors[::-1]
            actual = validate_capture(raw, rows[:2], model_binding(summary, plan, report, info['contract']['policy'], initial=initial),
                                      greedy, joint, control=expected, vectors=vectors)
            current = [dict(scores=o['scores'], raw={k: r.get(k) for k in ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')})
                       for o, r in zip(raw['occurrences'], actual, strict=True)]
            require(projection is None or current == projection, 'Dormant placeholder projections differ')
            projection = current; count += 2
    return count


def compare_prior_full_update(populations, trained_raw, trained_joint):
    observation_path = M / 'permission-retention-opening-science-observation-v01.json'
    observation_pin = pin(observation_path); observation = read(observation_path)
    require(observation['schema'] == 'permission-retention-opening-saved-science-observation/v1'
            and observation['passed'] is True and observation['findings'] == [], 'Predeclared prior-control science observation required')
    freeze_pin = checked_pin(observation['prior_freeze'], N2 / 'four-cell-output-freeze-v01.json')
    prior = read(Path(freeze_pin['path']))
    require(prior['schema'] == 'targeted-loss-four-cell-freeze/v1' and prior['all_four_outputs_frozen'] is True,
            'Prior four-cell frozen source control required')
    cells = [entry for entry in prior['cells'] if entry['cell']['id'] == 'rank0-presence1']
    require(len(cells) == 1, 'One exact prior actorOFF/presence1 control required')
    entry = cells[0]; summary_pin = checked_pin(entry['summary']); summary = read(Path(summary_pin['path']))
    require(summary['cell'] == dict(id='rank0-presence1', actor_ranking_enabled=False, presence_ce_weight=1, modality_loss_weight=2)
            and summary['actual_new_updates'] == 32 and summary['training_count'] == 168
            and summary['baseline_model_state_sha256'] == SOURCE_MODEL_SHA and summary['latent_enabled'] is False,
            'Prior matched full-update control differs')
    prior_saved = {}; panels = []
    for name, descriptor in zip(PANELS, summary['diagnostics'], strict=True):
        require(descriptor['name'] == name, 'Prior seven-panel ordering differs')
        left_path = Path(descriptor['raw']['path']); right_path = Path(descriptor['joint']['path'])
        for value, path in ((descriptor['raw'], left_path), (descriptor['joint'], right_path)):
            require(pair(checked_pin(value)) == entry['results'][str(path)], 'Prior frozen control capture drift')
            prior_saved[str(path)] = pair(value)
        before = read(left_path); before_joint = read(right_path)
        after, after_joint = trained_raw[name], trained_joint[name]
        vectors = compare_modalities(before['occurrences'], after['occurrences'], populations[name], require_equal=False)
        score_matches = []; raw_matches = []; joint_matches = []
        require(len(before['occurrences']) == len(before['inference']['rows']) == len(before_joint['rows']) == COUNTS[name],
                'Prior control complete source coverage required')
        for source, old, new, old_raw, new_raw, old_joint, new_joint in zip(populations[name], before['occurrences'], after['occurrences'],
                before['inference']['rows'], after['inference']['rows'], before_joint['rows'], after_joint['rows'], strict=True):
            require(old['id'] == new['id'] == old_joint['id'] == new_joint['id'] == source['id'], 'Prior control source ID alignment differs')
            score_matches.append(old['scores'] == new['scores'])
            keys = ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')
            raw_matches.append({k: old_raw.get(k) for k in keys} == {k: new_raw.get(k) for k in keys})
            joint_matches.append(old_joint['result'] == new_joint['result'])
        panels.append(dict(panel=name, rows=len(score_matches), modality_vectors=vectors,
                           all_head_score_payload_matches=sum(score_matches), raw_decision_matches=sum(raw_matches),
                           joint_decision_matches=sum(joint_matches), entire_panel_reproduced=all(score_matches + raw_matches + joint_matches)))
    return dict(preregistered_control='N2 rank0-presence1 actorOFF/presence1/modality2 full-parameter training',
                opening_science_observation=observation_pin, prior_freeze=freeze_pin, prior_summary=summary_pin,
                saved_capture_pins=prior_saved, panels=panels, source_rows=392,
                all392_saved_scores_and_decisions_reproduced=all(p['entire_panel_reproduced'] for p in panels),
                prior_initial_continuation_checkpoint_sha256=summary['initial_continuation_checkpoint_sha256'],
                full_model_tensor_state_reproduction_independently_tested=False,
                scope='Saved source-conditioned head payloads and raw/joint decisions only; opaque model checkpoints are not parsed')


def main(args):
    global OUTPUT, PACKET_ALLOWED
    opening_helper = pin(Path(__file__).resolve())
    require(pair(pin(N2_ANALYZER)) == N2_ANALYZER_PIN, 'Exact retained pure-analysis source required')
    require(pin(HELPER)['sha256'] == HELPER_SHA, 'Exact retained authored pair/scorer helper required')
    OUTPUT = Path(args.output).absolute()
    require(OUTPUT == M / 'permission-retention-result-analysis-v01.json' and OUTPUT.resolve() == OUTPUT and not OUTPUT.exists(),
            'Fresh exact owned analysis output required')
    manifest_path = Path(args.freeze_manifest).absolute()
    require(manifest_path == M / 'two-cell-output-freeze-v01.json', 'Exact two-cell output freeze required')
    manifest_pin = pin(manifest_path)
    require(type(args.freeze_manifest_sha256) is str and re.fullmatch(r'[0-9a-f]{64}', args.freeze_manifest_sha256)
            and manifest_pin['sha256'] == args.freeze_manifest_sha256, 'Explicit freeze raw SHA256 required')
    manifest = read(manifest_path)
    require(manifest['schema'] == 'permission-retention-two-cell-freeze/v1' and manifest['all_two_outputs_frozen'] is True
            and manifest['authorizes_authored_eval_scoring'] is True and manifest['new_pair_outputs_scored_before_freeze'] is False
            and manifest['reference_packet_previously_scored'] is True
            and manifest['freeze_scope'] == 'new_two_cell_outputs_only; references previously exposed'
            and manifest['independent_blinding'] is False and manifest['reference_builder_author_visible'] is True,
            'Explicit frozen-output authority and exposed-reference scope required')
    operational = {}
    for role, path in (('runner', RUNNER), ('registration', REGISTRATION), ('training_export', EXPORT)):
        actual = checked_pin(manifest[role], path); operational[str(path)] = pair(actual)
    require(pair(manifest['training_export']) == dict(bytes=5052701, sha256='a75b4125078d81aafabe1dcbe0e704da7386d859a019c158aef7ef1f7bb71f62'),
            'Byte-identical exposed prior168/seven-panel export required')
    registration, data = read(REGISTRATION), read(EXPORT)
    require(registration['schema'] == 'permission-retention-curriculum-registration/v1'
            and registration['data_export'] == manifest['training_export'] and registration['semantic_gold'] is False
            and registration['reference_packet_child_access'] is False and registration['previously_exposed_authored_evaluation'] is True
            and registration['independent_semantic_holdout'] is False, 'Exact exposed child-safe registration scope differs')
    require(manifest['reference_packet'] == registration['reference_packet']
            and manifest['reference_packet'] == dict(path=str(PACKET), bytes=8262146, sha256='b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e'),
            'Exact previously scored authored packet required')
    require(type(manifest['cells']) is list and len(manifest['cells']) == 2
            and {entry['cell']['id'] for entry in manifest['cells']} == set(CELLS), 'Exactly two distinct optimizer-policy cells required')
    require(len(registration['source_owner_pins']) == 32, 'Closed32-owner producer closure required')
    trainer_owner = registration['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_permission_retention']
    own, objective_validator = training_predicates(trainer_owner)
    helper_ns = detached(HELPER, {'validate_authored_pairs'}, dict(require=require, canonical=canonical, digest=digest, math=math,
        FIELDS=FIELDS, FALSE=FALSE, closed=lambda value, keys, label: require(type(value) is dict and set(value) == set(keys), 'Closed ' + label)))
    geometry = detached(RUNNER, {'validate_data'}, dict(require=require, canonical=canonical, digest=digest, math=math,
        DATA_SCHEMA='targeted-loss-curriculum-export/v1', REFERENCE_SCOPE='Authored engineering only; eval references excluded until all matrix outputs are frozen'))
    saved = {}; source_pins = {}; infos = {}; attempts = set()
    for entry in manifest['cells']:
        cell = entry['cell']; require(cell == expected_cell(cell['id']), 'Exact fixed-objective policy cell required')
        plan_path = M / (cell['id'] + '-plan-v01.json'); checked_pin(entry['plan'], plan_path); plan = read(plan_path)
        require(plan['schema'] == 'permission-retention-cell-plan/v1' and plan['cell'] == cell
                and plan['source_owner_pins'] == registration['source_owner_pins'] and plan['data_export'] == manifest['training_export']
                and plan['context_contract'] == registration['context_contract'] and plan['seed'] == plan['batch_order_seed'] == 1729
                and plan['dimension'] == 384 and plan['latent_enabled'] is False and plan['training_seconds'] == 32
                and plan['parent_base_canonical_sha256'] == SOURCE_PARENT_SHA and plan['parent_model_state_sha256'] == SOURCE_MODEL_SHA
                and plan['historical_parent_file_pin']['sha256'] == '5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb',
                'Exact parent/data/context/source-only configuration differs')
        require(type(plan['attempt_name']) is str and Path(plan['attempt_name']).name == plan['attempt_name']
                and plan['attempt_name'] not in attempts, 'Distinct canonical one-cell attempts required'); attempts.add(plan['attempt_name'])
        root = RUN_ROOT / plan['attempt_name'] / 'results'
        require(ordinary_inventory(root) == entry['results']
                and set(entry['results']) == expected_result_paths(root, cell['id'] == 'all-parameters'), 'Complete exact frozen result bundle differs')
        for path, value in entry['results'].items():
            require(set(value) == {'bytes', 'sha256'} and path not in saved, 'Closed distinct frozen output pins required'); saved[path] = value
        checked_pin(entry['summary'], root / 'summary.json')
        checked_pin(entry['guardian_terminal'], root.parent / 'guardian-exit.json'); checked_pin(entry['pre_admission'], root.parent / 'pre-admission.json')
        for role in ('plan', 'summary', 'guardian_terminal', 'pre_admission'):
            value = entry[role]; require(value['path'] not in operational, 'Repeated operational role refused'); operational[value['path']] = pair(value)
        terminal, pre = read(root.parent / 'guardian-exit.json'), read(root.parent / 'pre-admission.json')
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
                and terminal['returncode'] == terminal['child_returncode'] == 0
                and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
                'Successful durable released terminal required')
        require(pre['plan'] == entry['plan'] and pre['runner'] == manifest['runner'], 'Actual admitted plan/runner binding differs')
        summary = read(root / 'summary.json')
        require(summary['schema'] == 'permission-retention-cell-results/v1' and summary['status'] == 'completed'
                and summary['cell'] == cell and summary['attempt_name'] == plan['attempt_name']
                and summary['actual_new_updates'] == 32 and summary['actual_encoder_calls'] == 0
                and summary['fresh_Adam'] is True and summary['inherited_optimizer_moments'] is False
                and summary['parent_optimizer_steps'] == 400 and summary['training_count'] == 168
                and summary['configured_dimension'] == 384 and summary['latent_enabled'] is False
                and summary['baseline_optimizer_steps'] == 0 and summary['baseline_model_state_sha256'] == SOURCE_MODEL_SHA
                and summary['same_original_parent_model_sha256'] == SOURCE_MODEL_SHA
                and all(summary.get(k) is v for k, v in FALSE.items()), 'Completed equal-budget source-only summary differs')
        checkpoint = checked_pin(summary['checkpoint'], root / 'cell-checkpoint.json')
        training = checked_pin(summary['training'], root / 'cell-training.json')
        require(pair(checkpoint) == saved[checkpoint['path']] and pair(training) == saved[training['path']], 'Checkpoint/training is outside freeze')
        report = read(root / 'cell-training.json'); rows = geometry['validate_data'](plan, data, SimpleNamespace(validate_authored_pairs=helper_ns['validate_authored_pairs']))
        require(digest(rows) == 'afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34', 'Exact matched168 population required')
        contract = validate_training(summary, report, plan, rows, checkpoint, own, objective_validator)
        schedule_before = read(root / 'data-schedule-before-models.json')
        require(schedule_before['schedule'] == summary['prepared_schedule'] and schedule_before['training_count'] == 168
                and schedule_before['model_imported'] is False and all(schedule_before.get(k) is v for k, v in FALSE.items()), 'Saved pre-model schedule differs')
        require(summary['opening_owners'] == summary['closing_owners']
                and all(value == registration['source_owner_pins'][key] for key, value in summary['opening_owners'].items())
                and all('ipfs_datasets_py.optimizers.logic_theorem_optimizer.' + key in summary['opening_owners']
                        for key in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss', 'legal_span_permission_retention')),
                'Actual loaded trainer closure/source endpoints differ')
        for path, expected in plan['artifacts'].items():
            require(Path(path) != PACKET, 'Full reference packet must not enter numerical plan closure')
            if path in source_pins: require(source_pins[path] == expected, 'Conflicting immutable source closures')
            else: require(pair(pin(path)) == expected, 'Immutable source/artifact drift'); source_pins[path] = expected
        infos[cell['id']] = dict(entry=entry, plan=plan, summary=summary, report=report, contract=contract, result_root=root)
    require(len(saved) == 87, 'Exact two-cell87 output matrix required')
    first = infos['all-parameters']; first_summary = first['summary']
    for identifier, info in infos.items():
        reused = None if identifier == 'all-parameters' else first['entry']['summary']
        reused_plan = None if identifier == 'all-parameters' else first['entry']['plan']
        require(info['summary']['baseline_panels'] == first_summary['baseline_panels']
                and info['summary']['baseline_reuse'] == info['plan']['baseline_results'] == reused
                and info['plan']['baseline_plan'] == reused_plan
                and info['summary']['prepared_schedule'] == first_summary['prepared_schedule']
                and info['summary']['initial_continuation_checkpoint_sha256'] == first_summary['initial_continuation_checkpoint_sha256']
                and info['summary']['opening_owners'] == first_summary['opening_owners'], 'Exact common warm parent/baseline/schedule/source joins differ')
    require(infos['all-parameters']['summary']['initial_checkpoint_sha256'] != infos['span-heads-only']['summary']['initial_checkpoint_sha256'],
            'Authoritative distinct optimizer policies must not share a full outer checkpoint identity')
    for path, expected in {**saved, **source_pins, **operational}.items(): require(pair(pin(path)) == expected, 'Pre-scoring immutable artifact drift')
    require(pin(manifest_path) == manifest_pin and args.score_authored_eval is True, 'Explicit post-freeze authored scoring required')
    PACKET_ALLOWED = True
    packet_pin = checked_pin(manifest['reference_packet'], PACKET); packet = read(PACKET)
    require(packet['geometry_review_packet']['schema'] == 'targeted-loss-author-declaration-packet/v1'
            and packet['geometry_review_packet']['semantic_gold'] is False
            and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
            and packet['split_contract']['shared_authored_templates'] is True
            and packet['split_contract']['statutory_provision_holdout'] is False
            and all(value is False for value in packet['authority'].values()), 'Previously exposed authored reference authority differs')
    geometry_rows = packet['geometry_review_packet']['authored_eval']; require(len(geometry_rows) == 72, 'Complete authored72 reference rows required')
    populations = deepcopy(data['diagnostic_populations']); populations['authored_eval'] = [row['model_example'] for row in geometry_rows]
    metadata = deepcopy(data['diagnostic_metadata']); metadata['authored_eval'] = [{k: row[k] for k in ('id', 'class_name', 'group_id', 'pair_id', 'pair_variant')} for row in geometry_rows]
    require([{k: row[k] for k in ('id', 'source_text', 'latent')} for row in populations['authored_eval']] == data['diagnostic_populations']['authored_eval']
            and packet['training_populations'] == data['training_populations'] and packet['training_metadata'] == data['training_metadata']
            and packet['diagnostic_populations'] == data['diagnostic_populations'], 'Exposed packet/source/training joins differ')
    greedy, joint, scorer = reuse_scoring_predicates(registration['source_owner_pins'])
    table = []; row_maps = {}; captures = {}; joint_captures = {}
    states = [('baseline', first_summary['baseline_panels'], first['result_root'],
               model_binding(first_summary, first['plan'], first['report'], first['contract']['policy'], initial=True))]
    for identifier in CELLS:
        info = infos[identifier]
        states.append((identifier, info['summary']['diagnostics'], info['result_root'],
                       model_binding(info['summary'], info['plan'], info['report'], info['contract']['policy'], initial=False)))
    for state, descriptors, root, model in states:
        require([p['name'] for p in descriptors] == list(PANELS), 'Exact seven diagnostic panels required')
        captures[state] = {}; joint_captures[state] = {}
        for name, descriptor in zip(PANELS, descriptors, strict=True):
            panel, compact, raw, selected = analyze_panel(state, name, descriptor, populations[name], metadata.get(name), model,
                                                        greedy, joint, scorer, saved, root)
            table.append(panel); row_maps[state, name] = compact; captures[state][name] = raw; joint_captures[state][name] = selected
    modality_comparisons = {}; parity_observations = 0
    for identifier, info in infos.items():
        descriptor = checked_pin(info['summary']['modality_retention'], info['result_root'] / 'trained-modality-retention.json')
        require(pair(descriptor) == saved[descriptor['path']], 'Modality comparison is outside frozen bundle')
        modality_comparisons[identifier] = validate_modality_receipt(read(Path(descriptor['path'])), info['plan']['cell'],
            captures['baseline'], captures[identifier], data['diagnostic_populations'])
        parity_observations += validate_parity(info, data['diagnostic_populations']['fresh_tune'], greedy, joint, saved)
    prior_control = compare_prior_full_update(data['diagnostic_populations'], captures['all-parameters'], joint_captures['all-parameters'])
    require(prior_control['prior_initial_continuation_checkpoint_sha256'] == first_summary['initial_continuation_checkpoint_sha256'],
            'Prior and new immutable zero-update warm child identities differ')
    comparisons = []; gates = {}; differences = {}
    for identifier in CELLS:
        for name in PANELS[:-1]:
            baseline, current = row_maps['baseline', name], row_maps[identifier, name]
            require(set(baseline) == set(current), 'Same evaluated row identities required')
            comparisons.append(dict(cell=identifier, panel=name,
                raw_regressions=[key for key, row in current.items() if baseline[key]['raw_exact_ir'] and not row['raw_exact_ir']],
                raw_recoveries=[key for key, row in current.items() if not baseline[key]['raw_exact_ir'] and row['raw_exact_ir']],
                joint_regressions=[key for key, row in current.items() if baseline[key]['joint_exact_ir'] and not row['joint_exact_ir']],
                joint_recoveries=[key for key, row in current.items() if not baseline[key]['joint_exact_ir'] and row['joint_exact_ir']],
                changed_permission_rows=[dict(id=key, readout=readout, baseline_modality=baseline[key]['observed_modalities'][readout],
                                             trained_modality=row['observed_modalities'][readout])
                    for key, row in current.items() for readout in ('head_first_argmax', 'raw_decoded', 'joint_decoded')
                    if row['reference_modality'] == 'P' and baseline[key]['observed_modalities'][readout] != row['observed_modalities'][readout]]))
        old = next(p for p in table if p['state'] == identifier and p['panel'] == 'old_tune')
        permission = old['modalities']['permission_counts']
        gates[identifier] = dict(raw_exact_IR=old['raw_exact_IR'], joint_exact_IR=old['joint_exact_IR'],
            permission_counts=permission, exposed_legacy96_gate_met=old['raw_exact_IR'] == old['joint_exact_IR'] == 96
                and permission['raw_decoded']['P_to_O'] == permission['joint_decoded']['P_to_O'] == 0,
            necessary_engineering_gate_only=True, checkpoint_selected=False, promotion_performed=False)
    for name in PANELS[:-1]:
        arms = {identifier: next(p for p in table if p['state'] == identifier and p['panel'] == name) for identifier in CELLS}
        metrics = ('raw_exact_IR', 'joint_exact_IR', 'raw_abstentions', 'joint_abstentions', 'modality_exact', 'joint_modality_exact',
                   'temporal_presence_correct', 'temporal_false_positives', 'temporal_false_negatives')
        differences[name] = dict(rows=COUNTS[name], span_heads_only_minus_all_parameters={key: arms['span-heads-only'][key] - arms['all-parameters'][key] for key in metrics},
            permission_count_differences={readout: {key: arms['span-heads-only']['modalities']['permission_counts'][readout][key]
                - arms['all-parameters']['modalities']['permission_counts'][readout][key] for key in ('P_to_P', 'P_to_O', 'P_to_F', 'P_abstentions')}
                for readout in ('head_first_argmax', 'raw_decoded', 'joint_decoded')}, descriptive_one_seed_only=True)
    extra_roles = {str(N2_ANALYZER): N2_ANALYZER_PIN, str(HELPER): pair(pin(HELPER)),
                   prior_control['opening_science_observation']['path']: pair(prior_control['opening_science_observation']),
                   prior_control['prior_freeze']['path']: pair(prior_control['prior_freeze']),
                   prior_control['prior_summary']['path']: pair(prior_control['prior_summary'])}
    for path, expected in {**saved, **source_pins, **operational, **prior_control['saved_capture_pins'], **extra_roles}.items():
        require(pair(pin(path)) == expected, 'Closing frozen saved/source/operational/control artifact drift')
    for info in infos.values(): require(ordinary_inventory(info['result_root']) == info['entry']['results'], 'Closing complete result inventory drift')
    require(pin(manifest_path) == manifest_pin and pin(PACKET) == packet_pin and pin(Path(__file__).resolve()) == opening_helper,
            'Closing freeze/reference/helper artifact drift')
    result = dict(schema='permission-retention-two-cell-saved-result-analysis/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), helper=opening_helper, freeze_manifest=manifest_pin,
        reference_packet=packet_pin, reference_packet_previously_scored=True, independent_blinding=False,
        registration=manifest['registration'], training_export=manifest['training_export'], runner=manifest['runner'],
        saved_output_pins=saved, immutable_source_pins=source_pins, operational_freeze_role_pins=operational,
        additional_retained_source_and_control_role_pins=extra_roles,
        cell_contracts={identifier: info['contract'] for identifier, info in infos.items()},
        baseline_and_two_cell_panels=table, frozen_modality_comparisons=modality_comparisons,
        prior_full_update_control=prior_control, regressions_and_recoveries_relative_to_parent=comparisons,
        matched_parameter_policy_differences=differences, external_legacy96_gate_observations=gates,
        checkpoint_inventory={identifier: info['summary']['checkpoint'] for identifier, info in infos.items()},
        all_two_candidates_retained=True, selected_candidate_id=None, checkpoint_selection_performed=False, default_promotion=False,
        recorded_new_updates_total=64, parity_source_observations=parity_observations, scored_source_rows=1152,
        unscored_law_source_rows=24, source_only_dimension=384, latent_enabled=False, actual_encoder_calls_recorded=0,
        semantic_accuracy=None, statistical_significance_claimed=False,
        limitations=[
            'All reference panels are previously exposed authored engineering declarations and shared templates; no fresh blind/statutory holdout or independently reviewed USCode gold is claimed.',
            'One original400-step parent,168 rows,32 returned freshAdam updates per cell, and one seed/order1729. Descriptive matched differences do not establish seed robustness, statistical significance or general legal causality.',
            'The span-heads-only optimizer freezes17 shared/modality/dormant-latent tensors and updates6 presence/start/end tensors. Exact392 saved modality-vector retention preserves the parent head scores for these inputs; it does not guarantee full raw/joint IR retention or correctness.',
            'Teacher-forced batch scalar/frozen-parameter/gradient observations are trainer-reported evidence with source joins. No independent tensor/optimizer replay is performed and model checkpoints stay opaque.',
            'Permission head errors, decoded P→O/P→F and abstentions are reported separately, so abstention cannot hide a wrong modality head. Law8 is source-only and receives no invented reference or accuracy score.',
            'The legacy96 exact/permission gate is necessary engineering evidence only. Both candidates remain retained; no model selection or default promotion occurs.',
            'Configured384 conditioning is disabled and placeholder controls are not genuine8D/384D/768D latent evidence. Broader logic families, real legal fidelity and lake build legal remain unqualified.',
            'Pure saved-score joint/greedy/scoring replay uses named retained source predicates with bounded structural stubs, not a model execution or independent qualification of legal semantics. Separate resource audits cover sampled runtime/storage custody.'],
        analyzer_actions=dict(numerical_imports=0, model_restores=0, model_forwards=0, checkpoint_JSON_parses=0,
            optimizer_updates=0, resource_API_leases_locks=0, network_external_compiler_Git_HF_mutations=0,
            new_pair_scoring_only_after_complete_frozen_output_fences=True))
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-manifest', required=True)
    parser.add_argument('--freeze-manifest-sha256', required=True)
    parser.add_argument('--score-authored-eval', action='store_true')
    parser.add_argument('--output', required=True)
    main(parser.parse_args())

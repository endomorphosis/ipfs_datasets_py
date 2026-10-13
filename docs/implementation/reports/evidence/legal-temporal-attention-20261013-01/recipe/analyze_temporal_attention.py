"""Parent-only N7 scoring of a completed, durably frozen saved-output bundle.

No model, checkpoint JSON, numerical package, subprocess, network, resource API,
or compiler is used. Only named pure predicates are detached from pinned source.
Fresh references stay outside every model plan and are opened after freeze.
"""
from __future__ import annotations
import argparse
import ast
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

ROOT = Path(__file__).resolve().parent
N6 = ROOT.parent / 'legal-temporal-adapter-20261013-01'
N4 = ROOT.parent / 'legal-split-feature-20261013-01'
N2 = ROOT.parent / 'legal-targeted-loss-20261012-01'
T = ROOT.parent / 'legal-temporal-binding-20261012-01'
CONTRACT = ROOT / 'evaluation-contract-v01.json'
SOURCE_REVIEW = ROOT / 'analyzer-source-independent-review-v01.json'
OUTPUT = ROOT / 'temporal-attention-result-analysis-v01.json'
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
OLD_PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
FRESH_PANELS = ('fresh_dev', 'fresh_test')
PANELS = OLD_PANELS + FRESH_PANELS
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8, 36, 36), strict=True))
MODALITIES = ('O', 'P', 'F')
TRAINABLE = ('temporal_attention.query', 'temporal_presence.weight', 'temporal_presence.bias')
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
SOURCE_SHA = '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035'
SOURCE_STATE = 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5'
FIXED = {
    N6 / 'analyze_temporal_adapter.py': (45115, '08707ad592dfa62a0a6b0bfaa1f593625bd86d1617b2a304e37df611d5c1650d'),
    N6 / 'evaluation-contract-v01.json': (27955, '07a55d285882cac62207fb7008bbca55746c86a56c7aa3cd4a96374fdd6bf87e'),
    N6 / 'temporal-adapter-result-analysis-v01.json': (4092908, '3ae5a34286687bc35344c1ffaa09aa3b60d108d46604d983282168566f9302db'),
    N6 / 'result-independent-review-v01.json': (139520, '50abcbd7e5dc870cce5cd3a8442808228cef2211e53ded30fffa9a6c39bff7e2'),
    N6 / 'training-source-export-v01.json': (4675279, 'ea377724beeffcfc7e8565b03ed207a90cdf3a1955f4ba7d0bfea460ba94c3a9'),
    N6 / 'final-integration-independent-review-v01.json': (274169, '5c25eb3eca9a6bf1011e7b8baffa67c0f29c7c453ac0a8bb51259ddefbe1c729'),
    N2 / 'analyze_targeted_results_v01.py': (66275, '4274d682da303954689bbb318750a91a49b407961f26d718104e1890a0ae4d0f'),
    T / 'run_temporal_contrast_pilot.py': (42637, '0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'),
}
EXPECTED, OBSERVED = {}, {}
WRITING = False
FREEZE_PASSED = False
JOINT = None


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {
            'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py',
            'huggingface_hub', 'requests', 'resource', 'psutil', 'subprocess', 'socket'}:
        raise RuntimeError('Numerical, production, network and resource imports prohibited')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
            'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
            'os.mkdir', 'os.remove', 'os.rename', 'os.replace', 'os.rmdir', 'os.unlink',
            'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        raise RuntimeError('Process, network, resource and filesystem mutations prohibited')
    if event == 'os.chmod':
        require(WRITING and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444,
                'Only exclusive analysis output may be frozen')
    if event == 'open':
        path, mode, flags = args
        resolved = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        if resolved is not None:
            if resolved in {ROOT / 'fresh-reference-packet-v01.json', ROOT / 'fresh-reference-independent-review-v01.json'}:
                require(FREEZE_PASSED, 'Complete durable output freeze required before references')
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            require(WRITING and resolved == OUTPUT, 'Only exclusive owned analysis output write permitted')


def pin(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, 'Physical absolute input required')
    for part in (*reversed(path.parents), path):
        item = part.lstat()
        require(not stat.S_ISLNK(item.st_mode), 'Symlink input rejected')
        require(stat.S_ISREG(item.st_mode) if part == path else stat.S_ISDIR(item.st_mode), 'Ordinary input required')
    before = path.stat()
    hashed, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            hashed.update(block)
            size += len(block)
    after = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(after) and size == before.st_size, 'Input drift during hashing')
    actual = dict(bytes=size, sha256=hashed.hexdigest())
    if expected is not None:
        wanted = {k: expected[k] for k in ('bytes', 'sha256')}
        require(actual == wanted and ('path' not in expected or expected['path'] == str(path)), 'Input pin mismatch')
        require(str(path) not in EXPECTED or EXPECTED[str(path)] == wanted, 'Conflicting expected identity')
        EXPECTED[str(path)] = wanted
    require(str(path) not in OBSERVED or OBSERVED[str(path)] == actual, 'Input changed since opening')
    OBSERVED[str(path)] = actual
    return dict(path=str(path), **actual)


def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'private-runtime-snapshots' not in path.parts,
            'Checkpoint and private body parsing prohibited')
    captured = pin(path, expected)
    require(captured['bytes'] <= 16 * 1024 * 1024, 'Bounded JSON required')
    raw = path.read_bytes()
    require(len(raw) == captured['bytes'] and hashlib.sha256(raw).hexdigest() == captured['sha256'], 'Consumed bytes drift')
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    def finite(item):
        if type(item) is float:
            require(math.isfinite(item), 'Finite JSON floats required')
        elif type(item) is list:
            for child in item:
                finite(child)
        elif type(item) is dict:
            for child in item.values():
                finite(child)
    finite(value)
    pin(path, captured)
    return value


def detached(path, names, namespace):
    path = Path(path)
    require(str(path) in EXPECTED, 'Pinned source required before pure AST extraction')
    captured = pin(path, EXPECTED[str(path)])
    require(captured['bytes'] < 1024 * 1024, 'Bounded source required')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == captured['sha256'], 'Consumed source drift')
    nodes = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    require(len(nodes) == len(names) and {n.name for n in nodes} == set(names), 'Exact pure predicate set required')
    require(not any(n.decorator_list for n in nodes), 'Decorators prohibited')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    pin(path, captured)
    return namespace


def expected_results(root):
    names = {'summary.json', 'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json',
        'initial-parent-head-parity.json', 'trained-frozen-head-retention.json',
        'uniform-protected-head-retention.json', 'historical-control-protected-head-retention.json'}
    for state in ('baseline', 'trained'):
        names.update(f'{state}-{panel}-{kind}.json' for panel in PANELS for kind in ('raw', 'joint'))
    for label in ('parent-training168', 'initial-training168', 'trained-training168',
                  *(f'parent-{p}' for p in FRESH_PANELS), *(f'historical-control-{p}' for p in FRESH_PANELS),
                  *(f'uniform-{p}' for p in ('old_tune', *FRESH_PANELS))):
        names.update(f'{label}-{kind}.json' for kind in ('raw', 'joint'))
    for phase in ('initial', 'trained'):
        names.add(phase + '-parity.json')
        names.update(phase + '-parity-' + control + '.json'
                     for control in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    require(len(names) == 74, 'Exact74-file output geometry differs')
    return {str(root / name) for name in names}


def validate_freeze(freeze, freeze_path):
    require(freeze['schema'] == 'temporal-attention-output-freeze/v1'
        and freeze['all_outputs_frozen'] is True and freeze['authorizes_authored_eval_scoring'] is True
        and freeze['actual_returned_optimizer_updates'] == 32 and freeze['actual_new_control_optimizer_updates'] == 0,
        'Complete authorized N7 freeze required')
    require(freeze['evaluation_contract']['path'] == str(CONTRACT), 'Fixed evaluation contract path differs')
    for key in ('evaluation_contract', 'plan', 'summary', 'guardian_terminal', 'runtime_review'):
        pin(Path(freeze[key]['path']), freeze[key])
    root = Path(freeze['summary']['path']).parent
    require(root.is_dir() and set(freeze['results']) == expected_results(root), 'Closed74-file inventory required')
    require({str(p) for p in root.iterdir()} == set(freeze['results']), 'Unlisted result entry or missing file')
    for path, value in freeze['results'].items():
        require(Path(path).stat().st_mode & 0o222 == 0, 'Every result must be frozen read-only')
        pin(Path(path), value)
    require(freeze['results'][freeze['summary']['path']] == {k: freeze['summary'][k] for k in ('bytes', 'sha256')},
            'Summary/freeze identity differs')
    terminal = read(freeze['guardian_terminal']['path'], freeze['guardian_terminal'])
    require(terminal['schema'] == 'scope-pilot-guardian-exit/v1' and terminal['returncode'] == terminal['child_returncode'] == 0
        and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
        'Successful durable guardian terminal required')
    runtime = read(freeze['runtime_review']['path'], freeze['runtime_review'])
    require(runtime['passed'] is True and runtime['findings'] == [], 'Clean independent runtime review required')
    require(Path(freeze_path).stat().st_mode & 0o222 == 0, 'Durable freeze receipt must be read-only')
    return root


def bind_descriptor(descriptor, saved, expected_path=None):
    require(type(descriptor) is dict and set(descriptor) == {'path', 'bytes', 'sha256'}, 'Closed saved descriptor required')
    require(expected_path is None or descriptor['path'] == str(expected_path), 'Exact saved role/path required')
    require(saved[descriptor['path']] == {k: descriptor[k] for k in ('bytes', 'sha256')}, 'Descriptor/freeze join differs')
    return read(descriptor['path'], descriptor)


def source_projection(rows):
    return [{k: row[k] for k in ('id', 'source_text', 'latent')} for row in rows]


def validate_capture(raw, rows, greedy, *, summary=None, report=None, state=None, attention='learned', latent='none'):
    n = len(rows)
    require(len(raw['occurrences']) == len(raw['inference']['rows']) == n
        and raw['actual_source_forwards'] == n and raw['extra_capture_forwards'] == 0
        and raw['model_weights_unchanged'] is True and raw['original_greedy_observations_verified'] is True
        and raw['ambient_CPU_RNG_preserved'] is True and raw['target_access'] is False and raw['teacher_forcing'] is False
        and all(raw.get(k) is False for k in FALSE), 'Complete target-free capture required')
    inference = raw['inference']
    if summary is not None:
        checkpoint = summary['initial_checkpoint_sha256'] if state == 'initial' else summary['checkpoint']['sha256']
        model = summary['initial_model_state_sha256'] if state == 'initial' else summary['final_model_state_sha256']
        branches = report['initial_branch_digests'] if state == 'initial' else report['final_branch_digests']
        require(raw['schema'] == 'temporal-attention-adapter-target-free-head-capture/v1'
            and inference['schema'] == 'bounded-temporal-attention-adapter-inference/v1'
            and raw['attention_control'] == inference['attention_control'] == attention
            and inference['checkpoint_sha256'] == checkpoint and inference['model_state_sha256'] == model
            and inference['branch_digests'] == branches and inference['training_policy'] == report['training_policy']
            and inference['training_policy_sha256'] == digest(report['training_policy'])
            and inference['source_split_checkpoint_sha256'] == SOURCE_SHA
            and inference['source_split_model_state_sha256'] == SOURCE_STATE
            and inference['latent_ablation'] == latent, 'Candidate saved lineage/policy/control differs')
        for key in ('source_model_forwards', 'modality_encoder_forwards', 'span_encoder_forwards',
                    'original_presence_head_forwards', 'temporal_presence_head_forwards', 'attention_pool_forwards',
                    'temporal_mean_projection_forwards', 'temporal_attention_projection_forwards'):
            require(raw[key] == inference[key] == n, 'Exact capture forward accounting differs')
    require(inference['target_access'] is False and inference['teacher_forcing'] is False
            and inference['training_executed'] is False and all(inference.get(k) is False for k in FALSE),
            'Inference authority/target boundary differs')
    for source, occ, decoded in zip(rows, raw['occurrences'], inference['rows'], strict=True):
        sha = hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(source['id'] == occ['id'] and occ['source_sha256'] == decoded['source_sha256'] == sha,
                'Saved source ID/SHA256 join differs')
        require(decoded['latent_sha256'] == digest(source['latent']) and decoded['latent_input_enabled'] is False,
                'Dormant latent/source join differs')
        require(decoded['source_input_conditioned'] is True and decoded['sample_memory_used'] is False
            and decoded['training_executed'] is False and decoded['target_access'] is False
            and decoded['teacher_forcing'] is False and all(decoded.get(k) is False for k in FALSE),
            'Decoded source-only authority differs')
        JOINT['_validated'](source['source_text'], occ['scores'])
        greedy['_verify_greedy'](source['source_text'], occ['scores'], decoded)
    require(inference['decoded_count'] == sum(r['status'] == 'decoded' for r in inference['rows']), 'Decoded status count differs')


def validate_joint(value, raw, rows):
    require(value['schema'] in {'temporal-attention-joint-panel/v1', 'temporal-adapter-joint-panel/v1', 'split-feature-joint-panel/v1'}
        and value['top_k'] == 8 and value['max_search_nodes'] == 50000 and len(value['rows']) == len(rows),
        'Unchanged full joint panel geometry required')
    for source, occ, row in zip(rows, raw['occurrences'], value['rows'], strict=True):
        require(row['id'] == source['id'] and row['result'] == JOINT['select_joint_spans'](
            source['source_text'], occ['scores'], top_k=8, max_search_nodes=50000), 'Saved joint decision replay differs')
    return value['rows']


def compare_saved(rows, before, after, *, full, before_joint=None, after_joint=None):
    records = []
    require(len(before['occurrences']) == len(after['occurrences']) == len(rows), 'Complete parity coverage required')
    for i, (source, a, b) in enumerate(zip(rows, before['occurrences'], after['occurrences'], strict=True)):
        sha = hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(source['id'] == a['id'] == b['id'] and a['source_sha256'] == b['source_sha256'] == sha,
                'Parity source join differs')
        require(canonical(a['scores']['tokens']) == canonical(b['scores']['tokens']), 'Parity token boundaries differ')
        def projection(scores):
            return dict(modality_logits=scores['modality_logits'], start_logits=scores['start_logits'],
                end_logits=scores['end_logits'], presence_logits={k: v for k, v in scores['presence_logits'].items() if full or k != 'temporal'})
        left, right = projection(a['scores']), projection(b['scores'])
        require(floats(left) == floats(right), 'Required binary32 component parity failed')
        if full:
            keys = ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')
            require({k: before['inference']['rows'][i].get(k) for k in keys}
                == {k: after['inference']['rows'][i].get(k) for k in keys}, 'Initial greedy parent parity differs')
            require(before_joint[i] == after_joint[i], 'Initial joint parent parity differs')
        records.append(dict(id=source['id'], source_sha256=sha,
                            binary32_sha256=hashlib.sha256(floats(left)).hexdigest()))
    return records


def selection_gate(legacy, candidate_dev, historical_dev, technical):
    permissions = legacy['permission_outcomes']
    legacy_met = legacy['raw_exact_ir'] == legacy['joint_exact_ir'] == 96 and all(
        v == dict(P_to_P=32, P_to_O=0, P_to_F=0, P_abstentions=0) for v in permissions.values())
    metrics = ('temporal_presence_correct', 'joint_exact_ir')
    no_worse = all(candidate_dev[k] >= historical_dev[k] for k in metrics)
    better = any(candidate_dev[k] > historical_dev[k] for k in metrics)
    eligible = legacy_met and technical and no_worse and better
    return dict(eligible=eligible, selected_cell='temporal-attention-ce' if eligible else None,
        legacy_gate_passed=legacy_met, technical_gate_passed=technical,
        fresh_development_gate_passed=no_worse and better, both_development_metrics_no_worse=no_worse,
        at_least_one_development_metric_strictly_better=better,
        candidate_fresh_dev={k: candidate_dev[k] for k in metrics},
        historical_CE_fresh_dev={k: historical_dev[k] for k in metrics},
        comparison='Fixed completed N6 CE historical checkpoint, with zero new control optimizer updates',
        test_used_for_selection=False, threshold_or_hyperparameters_fitted=False,
        automatic_default_promotion=False, default_promotion=False)


def paired_changes(before, after):
    require([r['id'] for r in before] == [r['id'] for r in after], 'Exact paired ordered IDs required')
    result = {}
    for key in ('temporal_presence_correct', 'raw_exact_ir', 'joint_exact_ir'):
        result[key] = dict(before=sum(r[key] for r in before), after=sum(r[key] for r in after),
            recoveries=[a['id'] for a, b in zip(before, after, strict=True) if not a[key] and b[key]],
            regressions=[a['id'] for a, b in zip(before, after, strict=True) if a[key] and not b[key]])
    return result


def structural_validity(rows, raw, chosen, gold_coordinates):
    counts = {view: dict(decoded_or_selected=0, copied_single_rule_structurally_valid=0, invalid=0, abstained=0)
              for view in ('greedy', 'joint')}
    for source, g, j in zip(rows, raw['inference']['rows'], chosen, strict=True):
        for view, record, success in (('greedy', g, 'decoded'), ('joint', j['result'], 'selected')):
            value = counts[view]
            if record['status'] != success:
                require(record['canonical_ir'] is None, 'Abstention with nonnull canonical IR')
                value['abstained'] += 1
                continue
            value['decoded_or_selected'] += 1
            try:
                gold_coordinates(dict(source_text=source['source_text'], canonical_ir=record['canonical_ir']))
            except (ValueError, KeyError, TypeError):
                value['invalid'] += 1
            else:
                value['copied_single_rule_structurally_valid'] += 1
    return counts


def panel_score(panel, state, rows, metadata, raw, chosen, scorer, helpers, gold_coordinates):
    result = dict(panel=panel, state=state, row_count=len(rows), reference_scored=panel != 'law', semantic_accuracy=None)
    if panel == 'law':
        require(all('canonical_ir' not in r for r in rows), 'Statutory references forbidden')
        result.update(raw_exact_ir=None, joint_exact_ir=None, temporal_presence_correct=None,
            raw_abstentions=sum(r['status'] != 'decoded' for r in raw['inference']['rows']),
            joint_abstentions=sum(r['result']['status'] != 'selected' for r in chosen),
            scoring_status='UNSCORED_UNREVIEWED_STATUTORY8')
        return result, None
    score = scorer['score_panel'](rows, metadata, raw, chosen)
    result['scoring_status'] = ('FRESH_AUTHORED_ENGINEERING_ONLY' if panel in FRESH_PANELS else
                               'TRAINING_AUTHORED_ENGINEERING_ONLY' if panel == 'training168' else
                               'PREVIOUSLY_EXPOSED_AUTHORED_ENGINEERING_ONLY')
    result.update(helpers['compact_score'](score))
    result.update(helpers['confusion'](rows, raw, chosen))
    result['joint_abstentions'] = sum(r['result']['status'] != 'selected' for r in chosen)
    result['typed_structural_validity'] = structural_validity(rows, raw, chosen, gold_coordinates)
    result['temporal_heads'] = helpers['temporal_heads'](rows, metadata, raw, training=panel == 'training168')
    heads = result['temporal_heads']['rows']
    for h in heads:
        a, b = h['temporal_logits']
        h['raw_argmax_present'] = b > a
        h['exact_tie'] = a == b
        h['raw_argmax_correct'] = (b > a) is h['expected_present']
    result['temporal_raw_argmax_correct'] = sum(r['raw_argmax_correct'] for r in heads)
    result['temporal_exact_ties'] = sum(r['exact_tie'] for r in heads)
    result['temporal_confusion'] = {key: sum(
        r['predicted_present'] is pred and r['expected_present'] is expected for r in heads)
        for key, pred, expected in (('TP', True, True), ('TN', False, False), ('FP', True, False), ('FN', False, True))}
    result['temporal_confusion']['ambiguous'] = sum(r['predicted_present'] is None for r in heads)
    result['temporal_accuracy'] = score['temporal_presence_correct'] / len(rows)
    if panel in FRESH_PANELS:
        result['fresh_construction_groups'] = {}
        for group in sorted({m['group_id'] for m in metadata}):
            indices = [i for i, m in enumerate(metadata) if m['group_id'] == group]
            members = [score['rows'][i] for i in indices]
            result['fresh_construction_groups'][group] = dict(rows=len(indices),
                temporal_presence_correct=sum(r['temporal_presence_correct'] for r in members),
                raw_exact_ir=sum(r['raw_exact_ir'] for r in members), joint_exact_ir=sum(r['joint_exact_ir'] for r in members),
                temporal_false_positives=sum(r['temporal_false_positive'] for r in members),
                temporal_false_negatives=sum(r['temporal_false_negative'] for r in members),
                temporal_ambiguous=sum(r['temporal_ambiguous'] for r in members))
    return result, score['rows']


def pure_predicates(plan, base_names):
    helpers = detached(N6 / 'analyze_temporal_adapter.py',
        {'f32', 'floats', 'permission_summary', 'compact_score', 'confusion', 'temporal_heads', 'schedule'}, dict(globals()))
    namespace = dict(globals(), f32=helpers['f32'], HELPER=T / 'run_temporal_contrast_pilot.py',
                     HELPER_SHA=FIXED[T / 'run_temporal_contrast_pilot.py'][1])
    detached(N2 / 'analyze_targeted_results_v01.py', {'tokenize', 'strict_rule', 'gold_coordinates', 'scorers'}, namespace)
    greedy, joint, scorer = namespace['scorers'](plan['source_owner_pins'])
    helpers['JOINT'] = joint
    target = Path(plan['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_targeted_loss']['path'])
    targeted = detached(target, {'_require', '_raw', 'checkpoint_digest', '_policy', '_f32',
        '_span_coordinates', '_actor_domain', '_validate_objective_diagnostics'}, dict(copy=SimpleNamespace(deepcopy=deepcopy),
        hashlib=hashlib, json=json, math=math, struct=struct, SPAN_FIELDS=FIELDS, MAX_SOURCE_TOKENS=128,
        MAX_NEW_STEPS=32, MAX_SECONDS=32, POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
        LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
        span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z'))))
    attention_path = Path(plan['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_temporal_attention']['path'])
    attention = detached(attention_path, {'_partition', '_policy', '_validate_policy', '_stratum',
        '_validate_objective_entry', '_validate_freeze_entry'}, dict(_require=require, _raw=canonical, checkpoint_digest=digest,
        copy=SimpleNamespace(deepcopy=deepcopy), math=math, targeted=SimpleNamespace(**targeted),
        BASE_PARAMETER_NAMES=tuple(base_names), TRAINABLE_PARAMETER_NAMES=TRAINABLE,
        MODEL_PARAMETER_NAMES=tuple(base_names) + TRAINABLE, INACTIVE_ROWS=tuple(range(6)),
        ENCODED_WIDTH=64, STORED_TRAINABLE_SCALARS=1096, ACTIVE_TRAINABLE_SCALARS=322,
        OBJECTIVES=('temporal-attention-ce',), POLICY_SCHEMA='bounded-temporal-attention-adapter-policy/v1',
        STRATUM_COUNTS=dict(legacy_positive=48, legacy_negative=48, authored_positive=36, authored_negative=36),
        SOURCE_SPLIT_MODEL_SHA256=SOURCE_STATE, span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z'))))
    return namespace, greedy, joint, scorer, helpers, attention


def validate_training(summary, report, plan, rows, pure, helpers, gold_coordinates):
    policy = pure['_policy']('temporal-attention-ce')
    require(report['schema'] == 'bounded-temporal-attention-adapter-training/v1'
        and report['training_policy'] == policy and report['training_policy_sha256'] == digest(policy)
        and report['parameter_partition'] == pure['_partition']() and report['optimizer_parameter_order'] == list(TRAINABLE)
        and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
        and report['stopped_reason'] == 'step_limit' and report['training_executed'] is True
        and report['checkpoint_sha256'] == summary['checkpoint']['sha256']
        and report['previous_temporal_attention_checkpoint_sha256'] == summary['initial_checkpoint_sha256']
        and report['initial_model_state_sha256'] == report['training_call_initial_model_state_sha256'] == summary['initial_model_state_sha256']
        and report['final_model_state_sha256'] == summary['final_model_state_sha256']
        and report['source_split_checkpoint_sha256'] == SOURCE_SHA and report['source_split_model_state_sha256'] == SOURCE_STATE,
        'Fixed completed32 attention training lineage differs')
    schedule = helpers['schedule'](rows)
    require(summary['prepared_schedule'] == schedule, 'Fixed168 matched schedule differs')
    trace = report['batch_trace']
    batches, objectives, freezes = trace['batches'], report['objective_trace']['batches'], report['freeze_trace']['batches']
    require(trace['training_count'] == 168 and trace['completed_updates'] == 32
        and trace['training_manifest_sha256'] == digest(rows) and len(batches) == len(objectives) == len(freezes) == 32
        and [b['indices'] for b in batches] == schedule['batch_indices'] and [b['ids'] for b in batches] == schedule['batch_ids']
        and [b['loss'] for b in batches] == report['batch_losses']
        and report['objective_trace']['batches_sha256'] == digest(objectives)
        and report['freeze_trace']['batches_sha256'] == digest(freezes), 'Complete authenticated update trace differs')
    prior = None
    visits = dict(legacy_positive=0, legacy_negative=0, authored_positive=0, authored_negative=0)
    for step, (batch, objective, freeze) in enumerate(zip(batches, objectives, freezes, strict=True), 1):
        require(batch['optimizer_step'] == step, 'Returned update sequence differs')
        pure['_validate_objective_entry'](objective, batch, policy)
        pure['_validate_freeze_entry'](freeze, batch)
        require(prior is None or prior == freeze['branch_digests_before'], 'Inter-update branch continuity differs')
        prior = freeze['branch_digests_after']
        for index, entry, base in zip(batch['indices'], objective['details']['rows'], objective['details']['base_objective']['rows'], strict=True):
            source = rows[index]
            expected = bool(source['canonical_ir']['rules'][0]['temporal'])
            stratum = pure['_stratum'](index, expected)
            require(entry['id'] == source['id'] and entry['temporal_present'] is expected and entry['stratum'] == stratum,
                    'Training reference/stratum join differs')
            tokens, active = gold_coordinates(source)
            require(base['id'] == source['id'] and base['source_sha256'] == hashlib.sha256(source['source_text'].encode()).hexdigest()
                and base['token_count'] == len(tokens) and base['gold_coordinates'] == list(active['actor'])
                and base['present_gold_nonactor_coordinates'] == {f: list(v) for f, v in active.items() if f != 'actor'},
                'Actual training source/gold coordinates differ')
            visits[stratum] += 1
    require(report['frozen_base34_sha256_initial'] == report['frozen_base34_sha256_final'] == SOURCE_STATE
        and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final']
        and freezes[0]['branch_digests_before'] == report['training_call_initial_branch_digests']
        and freezes[-1]['branch_digests_after'] == report['final_branch_digests']
        and report['first_completed_update_query_gradient_zero'] is True, 'Frozen34/inactive rows/branch endpoint differs')
    accounting = report['forward_accounting']
    require(accounting['training_model_forward_calls'] == 32 and accounting['training_source_row_occurrences'] == 384
        and accounting['teacher_model_forward_calls'] == accounting['tuning_model_forward_calls'] == 0,
        'Training forward accounting differs')
    return dict(completed_updates=32, source_model_forward_calls=32, training_source_row_occurrences=384,
        stratum_visits=visits, original34_and_inactive_head_rows_fixed=True,
        first_query_gradient_exact_zero=True, independently_replayed_tensor_gradients_or_Adam_moments=False,
        evidence_scope='Pure scalar/source joins to source-bound saved trainer metadata; checkpoints remain opaque')


def main(args):
    global JOINT, OUTPUT, WRITING, FREEZE_PASSED, f32, floats
    OUTPUT = Path(args.output)
    require(OUTPUT.is_absolute() and OUTPUT.resolve() == OUTPUT and OUTPUT.parent == ROOT and not OUTPUT.exists(),
            'Fresh exclusive owned output required')
    source_review = read(SOURCE_REVIEW)
    require(source_review['schema'] == 'temporal-attention-analyzer-source-independent-review/v1'
        and source_review['passed'] is True and source_review['findings'] == []
        and source_review['analyzer'] == pin(Path(__file__).resolve()), 'Independent analyzer technical review required')
    for path, value in source_review['artifacts'].items():
        pin(Path(path), value)
    for path, (size, sha) in FIXED.items():
        pin(path, dict(bytes=size, sha256=sha))
    freeze_path = Path(args.freeze)
    freeze = read(freeze_path)
    result_root = validate_freeze(freeze, freeze_path)
    FREEZE_PASSED = True
    contract = read(CONTRACT, freeze['evaluation_contract'])
    require(contract['schema'] == 'temporal-attention-evaluation-contract/v1'
        and contract['score_only_after_complete_frozen_bundle'] is True and contract['references_parent_only'] is True
        and contract['default_promotion'] is False and contract['semantic_accuracy'] is None and contract['law8_unscored'] is True,
        'Frozen preregistered engineering contract required')
    plan = read(freeze['plan']['path'], freeze['plan'])
    summary = read(freeze['summary']['path'], freeze['summary'])
    require(plan['evaluation_contract'] == freeze['evaluation_contract'] and plan['default_promotion'] is False
        and summary['schema'] == 'temporal-attention-cell-results/v1' and summary['cell'] == 'temporal-attention-ce'
        and summary['status'] == 'completed' and summary['actual_new_updates'] == 32 and summary['actual_new_control_updates'] == 0
        and summary['source_checkpoint']['sha256'] == SOURCE_SHA and summary['source_model_state_sha256'] == SOURCE_STATE
        and summary['reference_scoring_performed'] is False and summary['diagnostic_reference_labels_in_child'] is False
        and summary['initial_and_final_training_labels_scored_by_child'] is False
        and summary['default_promotion'] is False and summary['checkpoint_selection_executed'] is False
        and all(summary.get(k) is False for k in FALSE), 'Complete source-only candidate envelope differs')
    require(summary['opening_owners'] == summary['closing_owners']
        and all(v == plan['source_owner_pins'].get(k) for k, v in summary['opening_owners'].items()), 'Loaded source closure differs')
    for descriptor in plan['source_owner_pins'].values():
        pin(Path(descriptor['path']), descriptor)
    require(not set(plan['artifacts']) & set(plan['forbidden_reference_paths'])
        and str(ROOT / 'fresh-reference-packet-v01.json') in plan['forbidden_reference_paths'], 'Fresh references entered model closure')
    data = read(plan['data_export']['path'], plan['data_export'])
    retained_data = read(N6 / 'training-source-export-v01.json', dict(bytes=FIXED[N6 / 'training-source-export-v01.json'][0], sha256=FIXED[N6 / 'training-source-export-v01.json'][1]))
    require(data == retained_data and len(data['training_rows']) == 168, 'Exact retained N6 training/source export required')
    rows = data['training_rows']
    n6contract = read(N6 / 'evaluation-contract-v01.json')
    n6fixed = read(N6 / 'temporal-adapter-result-analysis-v01.json')
    n6review = read(N6 / 'result-independent-review-v01.json')
    anchor = read(N6 / 'final-integration-independent-review-v01.json')
    require(n6fixed['passed'] is True and n6fixed['findings'] == [] and n6review['passed'] is True and n6review['findings'] == []
        and n6review['analysis'] == pin(N6 / 'temporal-adapter-result-analysis-v01.json')
        and anchor['passed'] is True and anchor['findings'] == [],
            'Qualified fixed historical analysis/anchor required')
    oldfreeze = read(plan['historical_control']['freeze']['path'], plan['historical_control']['freeze'])
    oldcell = next(c for c in oldfreeze['cells'] if c['cell'] == 'temporal-ce-control')
    require(oldfreeze['all_outputs_frozen'] is True and plan['historical_control']['summary'] == oldcell['summary'],
            'Fixed historical CE/freeze join differs')
    historical_summary = read(oldcell['summary']['path'], oldcell['summary'])
    require(summary['fixed_historical_control'] == plan['historical_control']
        and plan['historical_control']['new_optimizer_updates'] == 0
        and historical_summary['checkpoint'] == plan['historical_control']['checkpoint'], 'Historical fixed control identity differs')
    # Every new output pin was checked above; checkpoint files remain opaque.
    report = bind_descriptor(summary['training'], freeze['results'], result_root / 'cell-training.json')
    historical_report = read(plan['historical_control']['training']['path'], plan['historical_control']['training'])
    base_names = historical_report['parameter_partition']['frozen_parameter_names']
    require(len(base_names) == len(set(base_names)) == 34, 'Exact frozen34 parameter names required')
    namespace, greedy, JOINT, scorer, helpers, pure = pure_predicates(plan, base_names)
    f32, floats = helpers['f32'], helpers['floats']
    training = validate_training(summary, report, plan, rows, pure, helpers, namespace['gold_coordinates'])
    full_descriptor = oldfreeze['reference_source_export']
    require(n6contract['raw_artifact_pins'][full_descriptor['path']] == {k: full_descriptor[k] for k in ('bytes', 'sha256')},
            'Retained parent reference source pin differs')
    full = read(full_descriptor['path'], full_descriptor)
    populations, metadata = deepcopy(full['diagnostic_populations']), deepcopy(full['diagnostic_metadata'])
    old_packet = read(oldfreeze['reference_packet']['path'], oldfreeze['reference_packet'])
    populations['authored_eval'] = [r['model_example'] for r in old_packet['geometry_review_packet']['authored_eval']]
    metadata['authored_eval'] = [{k: r[k] for k in ('id', 'class_name', 'group_id', 'pair_id', 'pair_variant')}
                                for r in old_packet['geometry_review_packet']['authored_eval']]
    require({p: source_projection(populations[p]) for p in OLD_PANELS} == data['diagnostic_sources'],
            'Old392 source/reference join differs')
    fresh_source = read(contract['fresh_source_export']['path'], contract['fresh_source_export'])
    require(plan['fresh_source_export'] == contract['fresh_source_export'], 'Fresh source export identity differs')
    packet = read(contract['fresh_reference_packet']['path'], contract['fresh_reference_packet'])
    fresh_review = read(contract['fresh_reference_review']['path'], contract['fresh_reference_review'])
    require(fresh_review['passed'] is True and fresh_review['findings'] == [] and fresh_review['rows'] == 72
        and fresh_review['semantic_accuracy'] is None and fresh_review['independent_statutory_gold'] is False
        and fresh_review['artifacts'][str(ROOT / 'fresh-reference-packet-v01.json')] == contract['fresh_reference_packet']
        and packet['source_export'] == contract['fresh_source_export'], 'Reviewed fresh authored reference packet required')
    for panel in FRESH_PANELS:
        populations[panel] = [dict(r, latent=[0.] * 384) for r in packet['populations'][panel]]
        metadata[panel] = []
        for row, meta in zip(populations[panel], packet['metadata'][panel], strict=True):
            require(row['id'] == meta['id'] and meta['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
                and meta['main_action_temporal_present'] is bool(row['canonical_ir']['rules'][0]['temporal'])
                and meta['modality'] == row['canonical_ir']['rules'][0]['modality'], 'Fresh label/source metadata join differs')
            namespace['gold_coordinates'](row)
            metadata[panel].append(dict(id=row['id'], class_name=meta['lexical_construction'], group_id=meta['broad_group'],
                pair_id=meta['pair_id'], pair_variant='temporal_present' if meta['main_action_temporal_present'] else 'temporal_absent'))
        require(source_projection(populations[panel]) == fresh_source['populations'][panel]
            and len(populations[panel]) == 36 and len({m['group_id'] for m in metadata[panel]}) == 3,
            'Fresh36 source/reference/group coverage differs')
    require(not {m['group_id'] for m in metadata['fresh_dev']} & {m['group_id'] for m in metadata['fresh_test']}, 'Fresh group overlap')
    sources = {p: source_projection(populations[p]) for p in PANELS}
    all_sources = rows + sum((sources[p] for p in PANELS), [])
    require(len({r['id'] for r in all_sources}) == len({r['source_text'] for r in all_sources}) == 632, 'Exact distinct632 sources required')
    require(rows == full['training_populations']['mixed'] and data['training_metadata'] == full['training_metadata']['mixed'],
            'Exact retained168 training gold join differs')
    actual, scored, results = {}, {}, []
    def load_pair(descriptor, source_rows, label, *, candidate_state=None, attention='learned'):
        raw = bind_descriptor(descriptor['raw'], freeze['results'], result_root / (label + '-raw.json'))
        require(descriptor['row_count'] == len(source_rows), 'Pair source count differs')
        validate_capture(raw, source_rows, greedy, summary=summary if candidate_state else None,
                         report=report if candidate_state else None, state=candidate_state, attention=attention)
        chosen = validate_joint(bind_descriptor(descriptor['joint'], freeze['results'], result_root / (label + '-joint.json')), raw, source_rows)
        return raw, chosen
    for state, mapping in (('initial', summary['baseline_panels']), ('trained', summary['diagnostics'])):
        require(set(mapping) == set(PANELS), 'Complete464 candidate panel coverage required')
        for panel in PANELS:
            actual[state, panel] = load_pair(mapping[panel], sources[panel], ('baseline-' if state == 'initial' else 'trained-') + panel, candidate_state=state)
    for state, key, label in (('initial', 'initial_training_capture', 'initial-training168'),
                              ('trained', 'final_training_capture', 'trained-training168'),
                              ('parent', 'parent_training_capture', 'parent-training168')):
        actual[state, 'training168'] = load_pair(summary[key], rows, label, candidate_state=state if state != 'parent' else None)
    for panel in FRESH_PANELS:
        actual['parent', panel] = load_pair(summary['parent_fresh_panels'][panel], sources[panel], 'parent-' + panel)
        actual['historical_CE', panel] = load_pair(summary['historical_control_fresh_panels'][panel], sources[panel], 'historical-control-' + panel)
        require(actual['parent', panel][0]['inference']['checkpoint_sha256'] == SOURCE_SHA
            and actual['historical_CE', panel][0]['inference']['checkpoint_sha256'] == plan['historical_control']['checkpoint']['sha256'],
            'New fresh parent/historical fixed checkpoint join differs')
    require(actual['parent', 'training168'][0]['inference']['checkpoint_sha256'] == SOURCE_SHA, 'Training parent capture identity differs')
    for panel in ('old_tune', *FRESH_PANELS):
        actual['uniform', panel] = load_pair(summary['uniform_panels'][panel], sources[panel], 'uniform-' + panel, candidate_state='trained', attention='uniform')
    initial, protected = {}, {}
    for panel in OLD_PANELS:
        descriptor = plan['source_reference_panels'][panel]
        require(descriptor == n6contract['N4_trained_reference_captures'][panel], 'Exact previously qualified N4 reference capture differs')
        raw = read(descriptor['raw']['path'], descriptor['raw'])
        validate_capture(raw, sources[panel], greedy)
        chosen = validate_joint(read(descriptor['joint']['path'], descriptor['joint']), raw, sources[panel])
        actual['parent', panel] = raw, chosen
    for panel in (*PANELS, 'training168'):
        source_rows = rows if panel == 'training168' else sources[panel]
        before, before_joint = actual['parent', panel]
        baseline, baseline_joint = actual['initial', panel]
        final, final_joint = actual['trained', panel]
        initial[panel] = compare_saved(source_rows, before, baseline, full=True, before_joint=before_joint, after_joint=baseline_joint)
        protected[panel] = compare_saved(source_rows, baseline, final, full=False)
    require(sum(map(len, initial.values())) == sum(map(len, protected.values())) == 632, 'Independently recounted632 parity required')
    initial_receipt = bind_descriptor(summary['initial_parent_head_parity'], freeze['results'])
    final_receipt = bind_descriptor(summary['frozen_head_retention'], freeze['results'])
    require(initial_receipt['source_rows'] == final_receipt['source_rows'] == 632
        and initial_receipt['all_compared_components_bit_equal'] is True and final_receipt['all_compared_components_bit_equal'] is True
        and initial_receipt['optimizer_updates_before_gate'] == 0
        and initial_receipt['new240'] == sum((initial[p] for p in (*FRESH_PANELS, 'training168')), [])
        and final_receipt['rows'] == protected and final_receipt['compared_temporal_presence'] is False,
        'Recorded632 parity receipt differs from raw recount')
    old_rows = [dict(panel=p, **r, exact=True) for p in OLD_PANELS for r in initial[p]]
    require(initial_receipt['old392']['source_rows'] == 392 and initial_receipt['old392']['rows'] == old_rows,
            'Recorded old392 initial receipt differs')
    uniform_parity = {p: compare_saved(sources[p], actual['trained', p][0], actual['uniform', p][0], full=False)
                      for p in ('old_tune', *FRESH_PANELS)}
    uniform_receipt = read(result_root / 'uniform-protected-head-retention.json', freeze['results'][str(result_root / 'uniform-protected-head-retention.json')])
    require(uniform_receipt['source_rows'] == 168 and uniform_receipt['rows'] == uniform_parity
        and uniform_receipt['original_parameters_mutated'] is False, 'Uniform protected capture receipt differs')
    historical_parity = {p: compare_saved(sources[p], actual['parent', p][0], actual['historical_CE', p][0], full=False) for p in FRESH_PANELS}
    historical_receipt = read(result_root / 'historical-control-protected-head-retention.json', freeze['results'][str(result_root / 'historical-control-protected-head-retention.json')])
    require(historical_receipt['source_rows'] == 72 and historical_receipt['rows'] == historical_parity
        and historical_receipt['actual_new_optimizer_updates'] == 0, 'Historical fresh protected capture receipt differs')
    controls = []
    for phase, key in (('initial', 'initial_parity'), ('trained', 'trained_parity')):
        receipt = bind_descriptor(summary[key], freeze['results'], result_root / (phase + '-parity.json'))
        require(receipt['passed'] is True and receipt['source_count'] == 2 and receipt['genuine_latent_semantics_tested'] is False
            and receipt['actual_encoder_calls'] == 0, 'Dormant control receipt scope differs')
        names = ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders')
        require([r['name'] for r in receipt['controls']] == list(names), 'All four fixed dormant controls required')
        first = None
        for item in receipt['controls']:
            source_rows = deepcopy(sources['fresh_tune'][:2])
            for i, row in enumerate(source_rows):
                row['latent'] = [0. if item['name'] == 'zeros' else .25 if i == 0 else -.25] * 384
            if item['name'] == 'rotated_placeholders':
                source_rows[0]['latent'], source_rows[1]['latent'] = source_rows[1]['latent'], source_rows[0]['latent']
            raw = bind_descriptor(item['report'], freeze['results'], result_root / (phase + '-parity-' + item['name'] + '.json'))
            validate_capture(raw, source_rows, greedy, summary=summary, report=report, state=phase, latent=item['control'])
            projection = [dict(scores=o['scores'], raw={k: r.get(k) for k in
                ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')})
                for o, r in zip(raw['occurrences'], raw['inference']['rows'], strict=True)]
            require(first is None or canonical(first) == canonical(projection), 'Dormant control readout parity differs')
            first = projection
        controls.append(dict(phase=phase, controls=4, rows_each=2, invariant=True, genuine_latent_semantics_tested=False))
    for (state, panel), (raw, chosen) in actual.items():
        if state == 'parent' and panel in OLD_PANELS:
            continue
        source_rows = rows if panel == 'training168' else populations[panel]
        meta = data['training_metadata'] if panel == 'training168' else metadata.get(panel)
        result, row_scores = panel_score(panel, state, source_rows, meta, raw, chosen, scorer, helpers, namespace['gold_coordinates'])
        results.append(result)
        if row_scores is not None:
            scored[state, panel] = row_scores
    # Reuse historical N6 saved predictions, not a newly initialized control.
    for panel, descriptor in zip(OLD_PANELS, historical_summary['diagnostics'], strict=True):
        require(descriptor['name'] == panel, 'Fixed historical panel order differs')
        for kind in ('raw', 'joint'):
            require(oldcell['results'][descriptor[kind]['path']] == {k: descriptor[kind][k] for k in ('bytes', 'sha256')},
                    'Old historical capture/freeze join differs')
        raw = read(descriptor['raw']['path'], descriptor['raw'])
        validate_capture(raw, sources[panel], greedy)
        chosen = validate_joint(read(descriptor['joint']['path'], descriptor['joint']), raw, sources[panel])
        require(raw['inference']['checkpoint_sha256'] == plan['historical_control']['checkpoint']['sha256'], 'Saved historical checkpoint differs')
        result, row_scores = panel_score(panel, 'historical_CE', populations[panel], metadata.get(panel), raw, chosen, scorer, helpers, namespace['gold_coordinates'])
        results.append(result)
        if row_scores is not None:
            require(row_scores == n6fixed['scored_rows']['temporal-ce-control']['trained'][panel], 'Fixed N6 score recount differs')
            scored['historical_CE', panel] = row_scores
    comparisons = []
    for panel in (*[p for p in PANELS if p != 'law'], 'training168'):
        comparisons.append(dict(panel=panel, before='initial', after='trained', changes=paired_changes(scored['initial', panel], scored['trained', panel])))
    for panel in ('old_tune', *FRESH_PANELS):
        comparisons.append(dict(panel=panel, before='trained', after='uniform',
            scope='Inference attention dependence; no causal training attribution', changes=paired_changes(scored['trained', panel], scored['uniform', panel])))
    for panel in [p for p in PANELS if p != 'law']:
        comparisons.append(dict(panel=panel, before='historical_CE', after='trained', changes=paired_changes(scored['historical_CE', panel], scored['trained', panel])))
    find = lambda state, panel: next(r for r in results if r['state'] == state and r['panel'] == panel)
    selection = selection_gate(find('trained', 'old_tune'), find('trained', 'fresh_dev'), find('historical_CE', 'fresh_dev'), technical=True)
    require(summary['candidate_diagnostic_source_forwards'] == 928 and summary['candidate_training_capture_source_forwards'] == 336
        and summary['candidate_uniform_source_forwards'] == 168 and summary['parent_extra_source_forwards'] == 240
        and summary['historical_control_source_forwards'] == 72 and summary['dormant_control_source_forwards'] == 16
        and summary['total_inference_source_forwards'] == 1760 and summary['actual_training_model_forwards'] == 32
        and summary['total_actual_model_forwards'] == 1792 and summary['actual_external_encoder_calls'] == 0,
        'Actual model/inference accounting differs')
    own = pin(Path(__file__).resolve())
    for path, value in list(OBSERVED.items()):
        pin(Path(path), value)
    analysis = dict(schema='temporal-attention-frozen-result-analysis/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), analyzer=own, evaluation_contract=pin(CONTRACT),
        freeze=pin(freeze_path), independent_source_review=pin(SOURCE_REVIEW), runtime_review=freeze['runtime_review'],
        fresh_reference_review=contract['fresh_reference_review'], panel_results=results, paired_comparisons=comparisons,
        engineering_selection=selection, initial_full_head_parity=initial, trained_protected_head_retention=protected,
        initial_parity_source_rows=632, trained_retention_source_rows=632, uniform_protected_retention=uniform_parity,
        fixed_historical_CE_fresh_protected_retention=historical_parity, training_metadata=training, dormant_controls=controls,
        scored_rows={state: {panel: values for (s, panel), values in scored.items() if s == state} for state in sorted({s for s, p in scored})},
        fresh_development_rows=36, fresh_test_rows=36, test_used_for_selection=False, old392_previously_exposed=True,
        actual_new_candidate_optimizer_updates=32, actual_new_control_optimizer_updates=0,
        fixed_historical_control_not_new_randomized_run=True, equal_compute_budget_claimed=False,
        new_model_forwards_by_analysis=0, new_optimizer_updates_by_analysis=0, checkpoint_JSON_parses=0,
        numerical_imports=0, network_requests=0, resource_API_calls=0, compiler_calls=0,
        default_promotion=False, semantic_accuracy=None, independent_statutory_gold=False,
        genuine_latent_semantics_qualified=False, broader_logic_families_qualified=False, Lake_executed=False,
        unscored_populations=dict(law=dict(rows=8, status='UNSCORED_UNREVIEWED_STATUTORY8', semantic_accuracy=None)),
        unsupported_markers=dict(genuine8D='UNSUPPORTED', genuine384D='UNSUPPORTED', genuine768D='UNSUPPORTED',
            broad_family='UNSUPPORTED', Lake='NOT_EXECUTED', legal_semantic_accuracy='UNSCORED'),
        limitations=contract['evidence_limits'] + [
            'Fresh packet author draft status is superseded only by its separately pinned root engineering review; no independent legal expert gold.',
            'Guarded temporal correct counts retain the existing1e-7 readout guard; unguarded saved-score argmax and exact ties are exposed separately.',
            'Frozen tensor/gradient/moment invariants are saved source-bound trainer metadata; no checkpoint tensor or Adam moment replay.',
            'Engineering eligibility never promotes the default decoder; statutory8 stay unscored.'],
        input_pins=OBSERVED, closing_raw_pins_unchanged=True, **FALSE)
    raw = json.dumps(analysis, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
    require(len(raw) < 24 * 1024 * 1024, 'Finite analysis storage bound exceeded')
    WRITING = True
    with OUTPUT.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(output=str(OUTPUT), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                          engineering_selection=selection), sort_keys=True))


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', required=True)
    parser.add_argument('--output', default=str(OUTPUT))
    main(parser.parse_args())

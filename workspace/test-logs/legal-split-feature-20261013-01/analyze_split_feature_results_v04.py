"""Analyze one frozen split-feature run using saved scores and reported metadata only.

No numerical imports, model execution, checkpoint JSON parser, compiler, network,
resource API or Git mutation. References are previously exposed authored targets.
"""
from __future__ import annotations
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
import re
import random
import stat
import struct
import sys
from types import SimpleNamespace

M = Path(__file__).resolve().parent
N3 = M.parent / 'legal-permission-retention-20261012-01'
N2 = M.parent / 'legal-targeted-loss-20261012-01'
T = M.parent / 'legal-temporal-binding-20261012-01'
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
COUNTS = dict(old_tune=96, fresh_tune=36, fresh_challenge=36, old_authored_eval=72, authored_dev=72, authored_eval=72, law=8)
MODALITIES = ('O', 'P', 'F')
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
SOURCE_PARENT_SHA = 'fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279'
SOURCE_MODEL_SHA = '54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb'
HELPER = T / 'run_temporal_contrast_pilot.py'
HELPER_SHA = '0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'
PACKET = N2 / 'authored-reference-packet-v01.json'
OUTPUT = M / 'split-feature-result-analysis-v01.json'
APPROVAL = M / 'split-feature-analyzer-source-independent-review-v02.json'
EXPECTED = {
    str(N3 / 'two-cell-output-freeze-v01.json'): dict(bytes=33463, sha256='2a268b4b3f5c03cedb29d8d1df6d5718778fc54da9473fabfb5c2eaefde7d46b'),
    str(N3 / 'permission-retention-result-analysis-v01.json'): dict(bytes=1638365, sha256='b8db48da856b2cc6308b75b2d456dc2e7fe92e876659b98f19846456c6d84e15'),
    str(N3 / 'result-independent-review-v01.json'): dict(bytes=87546, sha256='002bbe70e45d1c3b38b27adcc4328d05d640beab5f069b1826b7af55d32fa21e'),
    str(N3 / 'runtime-independent-review-v01.json'): dict(bytes=59468, sha256='eb3dc46a2924941e06837351606a080225cd1c01d951d27603f5e3e6bbe3f2a0'),
    str(N3 / 'final-permission-retention-integration-independent-review-v01.json'): dict(bytes=115893, sha256='b863307c5e6852eb6f6f9f4a7a7fa7629862a9b7982888441317aae2b62c6f87'),
    str(N3 / 'analyze_permission_retention_v01.py'): dict(bytes=69075, sha256='4e74c5fc209187b37ed573facd606a57ecd2fe020ad36924f00f32bf0e6912b4'),
    str(N2 / 'analyze_targeted_results_v01.py'): dict(bytes=66275, sha256='4274d682da303954689bbb318750a91a49b407961f26d718104e1890a0ae4d0f'),
    str(HELPER): dict(bytes=42637, sha256=HELPER_SHA),
    str(N3 / 'datasets/docs/autoencoders/permission_retention_training_gaps_20261012.md'): dict(bytes=4671, sha256='e4cc1cf2b99773080617f0af30af939fe78de3b1e4a97fc4d5b6a8febb2fad2a'),
}
TRAINER = M / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py'
TARGETED = M / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_targeted_loss.py'
RUNNER = M / 'run_split_features.py'
FREEZER = M / 'freeze_split_outputs_v02.py'
HYBRID_SOURCE = M / 'analyze_saved_score_hybrid_v02.py'
HYBRID_OUTPUT = M / 'saved-score-hybrid-analysis-v01.json'
FROZEN17_SHA = '83c5d0760e869cc817c979ce5fc928a8bd6d67e12ef9d5a6cfe24937bf054d8d'
EXPECTED.update({
 str(TRAINER): dict(bytes=52067, sha256='886a0cde9924dceb5f5a4b655a995eb60a8f3fb954408d991fe4b4eb23ade0cd'),
 str(RUNNER): dict(bytes=38053, sha256='abedfe1505c3c554deac3b79d6516062a0d8b4589510522f812ebee07ce2d19a'),
 str(FREEZER): dict(bytes=5841, sha256='cd9fcaf43603dc182a7f89a9660d2a53b6b749f4286c45e0a6884166e23ea3ce'),
 str(M / 'terminal-copy-freeze-source-independent-review-v02.json'): dict(bytes=4970, sha256='2c1caba2c13c6c71eb9009eee1b66f996763ea57f950b40b7b7dac4a0ff09489'),
 str(M / 'split-feature-output-freeze-v01.json'): dict(bytes=20150, sha256='bcefd26d2b7ec9d96fd28d46ee3b6e69728d49a4cf13ababe50036a1d648c33b'),
 str(HYBRID_SOURCE): dict(bytes=34453, sha256='bb1cf7a857e6aff04bfb1567256689257956f7c597201d570820d278e0a724a4'),
 str(HYBRID_OUTPUT): dict(bytes=16244552, sha256='8e4a2dec5d63379c27684255e4f2e040f094d73cd70fc64fc050df1e9437d22f'),
 str(M / 'saved-score-hybrid-source-independent-review-v02.json'): dict(bytes=3464, sha256='b06f1914c11589395f92ba8a6934d397696db6f1f5c0d787ec254c2164da2032'),
 str(M / 'split-feature-evaluation-contract-v01.json'): dict(bytes=9047, sha256='2e9f213f87fd755b3bb22658e08516b12f8e43a0c5b42e5c345dacdd1a8559c0'),
})
OBSERVED = {}
PACKET_ALLOWED = False
WRITES_ALLOWED = False
MAX_JSON_BYTES = 128 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'}:
        raise AssertionError('Split-feature saved-result analysis forbids numerical/production imports')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
        'os.mkdir', 'os.remove', 'os.rename', 'os.replace', 'os.rmdir', 'os.unlink'}:
        raise AssertionError('Split-feature saved-result analysis forbids process/network/resource/filesystem mutations')
    if event in {'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        path = args[0] if args else None
        resolved = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        if not (event == 'os.chmod' and WRITES_ALLOWED and resolved == OUTPUT and args[1] == 0o444):
            raise AssertionError('Only the exclusive new output may be frozen; other metadata mutations are forbidden')
    if event == 'open':
        path, mode, flags = args
        resolved = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        if resolved == PACKET and not PACKET_ALLOWED:
            raise AssertionError('Frozen inventory and qualified-source fences required before reference access')
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and (not WRITES_ALLOWED or resolved != OUTPUT):
            raise AssertionError('Only the exclusive new diagnostic output may be written')


sys.dont_write_bytecode = True
sys.addaudithook(audit)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pair(value):
    return {key: value[key] for key in ('bytes', 'sha256')}


def physical(path):
    require(path.is_absolute() and path.resolve() == path, 'absolute physical path required')
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'symlink input refused')
        require(stat.S_ISREG(info.st_mode) if part == path else stat.S_ISDIR(info.st_mode), 'ordinary input required')


def pin(path):
    path = Path(path)
    physical(path)
    before = path.stat()
    hashed = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk)
            hashed.update(chunk)
    after = path.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    require(identity(before) == identity(after), 'input changed while raw-pinned')
    value = dict(bytes=size, sha256=hashed.hexdigest())
    require(str(path) not in EXPECTED or EXPECTED[str(path)] == value, 'expected input identity differs')
    require(str(path) not in OBSERVED or OBSERVED[str(path)] == value, 'previously observed input changed')
    OBSERVED[str(path)] = value
    return dict(path=str(path), **value)


def register(value, expected_path=None):
    require(type(value) is dict and set(value) == {'path', 'bytes', 'sha256'}, 'closed raw descriptor required')
    path = Path(value['path'])
    require(expected_path is None or path == expected_path, 'exact descriptor path differs')
    require(type(value['bytes']) is int and value['bytes'] >= 0 and type(value['sha256']) is str
            and len(value['sha256']) == 64 and all(c in '0123456789abcdef' for c in value['sha256']), 'exact raw descriptor required')
    require(str(path) not in EXPECTED or EXPECTED[str(path)] == pair(value), 'conflicting expected input pins')
    EXPECTED[str(path)] = pair(value)
    require(pin(path) == value, 'raw descriptor differs')
    return value


def checked_pin(value, expected_path=None):
    return register(value, expected_path)


def captured_bytes(path, limit):
    path = Path(path)
    require(str(path) in EXPECTED and str(path) in OBSERVED, 'opening expected and observed raw pins required')
    expected = EXPECTED[str(path)]
    require(path.stat().st_size == expected['bytes'] <= limit, 'bounded expected input required before allocation')
    raw = path.read_bytes()
    require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == expected, 'consumed bytes differ from opening expected pin')
    require(pair(pin(path)) == expected, 'input changed after consumption')
    return raw


def read(path):
    path = Path(path)
    require('checkpoint' not in path.name and 'private-runtime-snapshots' not in path.parts,
            'checkpoint and private-body JSON parsing prohibited')
    raw = captured_bytes(path, MAX_JSON_BYTES)

    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def reject(value):
        raise ValueError('nonfinite JSON constant: ' + value)

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)

    def finite(item):
        if type(item) is float:
            require(math.isfinite(item), 'finite JSON scalars required')
        elif type(item) is list:
            for child in item:
                finite(child)
        elif type(item) is dict:
            for child in item.values():
                finite(child)
    finite(value)
    return value


def detached(path, names, namespace):
    raw = captured_bytes(Path(path), 2 * 1024 * 1024)
    tree = ast.parse(raw)
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    require(len(selected) == len(names) and {node.name for node in selected} == set(names), 'exact retained predicate names required')
    require(not any(getattr(node, 'decorator_list', []) for node in selected), 'detached decorators refused')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def inventory(root):
    result = {}
    for path in root.iterdir():
        require(path.is_file() and not path.is_symlink() and path.suffix == '.json', 'ordinary flat result file required')
        require(len(result) < 100, 'bounded result inventory required')
        result[str(path)] = pair(pin(path))
    return result


def score_bytes(scores, fields):
    """Fixed-order IEEE754 bytes for logits only, preserving signed zero."""
    values = []
    for field in fields:
        value = scores[field]
        if field == 'modality_logits':
            require(type(value) is list and len(value) == 3, 'three modality logits required')
            values.extend(value)
        else:
            order = FIELDS[2:] if field == 'presence_logits' else FIELDS
            require(type(value) is dict and set(value) == set(order), 'closed facet logit fields required')
            for facet in order:
                require(type(value[facet]) is list and len(value[facet]) == (2 if field == 'presence_logits' else len(scores['tokens'])),
                        'complete saved score width required')
                values.extend(value[facet])
    result = bytearray()
    for value in values:
        require(type(value) is float and math.isfinite(value), 'finite float logit required')
        try:
            raw = struct.pack('<f', value)
        except (OverflowError, struct.error):
            raise ValueError('binary32 logit required') from None
        require(struct.unpack('<f', raw)[0] == value, 'saved logits must already be binary32')
        result.extend(raw)
    return bytes(result)


def validate_capture(raw, rows, model, greedy, joint, *, control='none', vectors=None):
    require(raw['schema'] == 'split-feature-target-free-head-capture/v1'
            and raw['actual_source_forwards'] == len(rows) and raw['extra_capture_forwards'] == 0
            and raw['target_access'] is False and raw['teacher_forcing'] is False
            and raw['model_weights_unchanged'] is True and raw['original_greedy_observations_verified'] is True
            and raw['ambient_CPU_RNG_preserved'] is True and all(raw.get(k) is v for k, v in FALSE.items()),
            'Saved target-free capture scope differs')
    require(all(type(raw[key]) is int and raw[key] == len(rows) for key in ('source_model_forwards', 'modality_encoder_forwards', 'span_encoder_forwards')), 'Two explicit source feature paths required per capture')
    inference = raw['inference']
    require(inference['schema'] == 'bounded-split-feature-span-legal-formula-inference/v1'
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
    require(inference['split_feature_model_forward'] is True and inference['branch_digests'] == model['branch_digests']
            and all(type(inference[key]) is int and inference[key] == len(rows) for key in ('source_model_forwards', 'modality_encoder_forwards', 'span_encoder_forwards')), 'Saved split-feature branches/forward accounting differ')
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
    require(selected['schema'] == 'split-feature-joint-panel/v1'
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

def differences(parent, current):
    require(set(parent) == set(current), 'complete matched score identities required')
    return dict(raw_regressions=[key for key in parent if parent[key]['raw_exact_ir'] and not current[key]['raw_exact_ir']],
                raw_recoveries=[key for key in parent if not parent[key]['raw_exact_ir'] and current[key]['raw_exact_ir']],
                joint_regressions=[key for key in parent if parent[key]['joint_exact_ir'] and not current[key]['joint_exact_ir']],
                joint_recoveries=[key for key in parent if not parent[key]['joint_exact_ir'] and current[key]['joint_exact_ir']])

def expected_result_paths(root):
    names = {'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json', 'summary.json', 'trained-modality-retention.json'}
    for stage in ('initial', 'trained'):
        names.add(stage + '-parity.json')
        names.update(stage + '-parity-' + control + '.json' for control in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    for state in ('baseline', 'trained'):
        for panel in PANELS:
            names.update(state + '-' + panel + '-' + kind + '.json' for kind in ('raw', 'joint'))
            if panel not in ('authored_eval', 'law'): names.add(state + '-' + panel + '-score.json')
    return {str(root / name) for name in names}

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

def source_constants(path, names):
    """Read only literal parameter-name constants; never import the module."""
    tree = ast.parse(captured_bytes(path, 2 * 1024 * 1024))
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            result[node.targets[0].id] = ast.literal_eval(node.value)
    require(set(result) == set(names), 'Exact literal source constants required')
    return result


def policy_predicates(owners):
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    require(owners[prefix + 'legal_span_split_features']['path'] == str(TRAINER), 'Exact new trainer origin required')
    require(owners[prefix + 'legal_span_targeted_loss']['path'] == str(TARGETED), 'Exact retained objective origin required')
    constants = source_constants(TRAINER, {'ORIGINAL_PARAMETER_NAMES', 'FACET_PARAMETER_NAMES', 'FEATURE_PARAMETER_NAMES', 'LATENT_PARAMETER_NAMES', 'BRANCH_DIGEST_FIELDS'})
    constants['SPLIT_FEATURE_PARAMETER_NAMES'] = tuple('span_' + name for name in constants['FEATURE_PARAMETER_NAMES'])
    constants['MODEL_PARAMETER_NAMES'] = constants['ORIGINAL_PARAMETER_NAMES'] + constants['SPLIT_FEATURE_PARAMETER_NAMES']
    constants['TRAINABLE_PARAMETER_NAMES'] = constants['SPLIT_FEATURE_PARAMETER_NAMES'] + constants['FACET_PARAMETER_NAMES']
    common = dict(_require=require, _raw=canonical, checkpoint_digest=digest, copy=SimpleNamespace(deepcopy=deepcopy),
                  hashlib=hashlib, json=json, math=math, struct=struct, SPAN_FIELDS=FIELDS, MAX_SOURCE_TOKENS=128,
                  MAX_NEW_STEPS=32, MAX_SECONDS=32, POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
                  LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
                  span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z')))
    objective = detached(TARGETED, {'_policy', '_validate_policy', '_f32', '_span_coordinates', '_actor_domain',
                                 '_validate_objective_diagnostics', '_objective_trace_summary'}, dict(common))
    own = dict(common, **constants, targeted=SimpleNamespace(**{name: objective[name] for name in ('_policy', '_f32')}))
    own['POLICY_SCHEMA'] = 'bounded-source-span-split-feature-policy/v1'
    detached(TRAINER, {'_partition', '_policy', '_validate_policy', '_modal_rows', '_validate_branch_pair', '_freeze_entry', '_freeze_summary', '_constant_entry', '_constant_summary'}, own)
    retained = dict(globals(), targeted_pure=lambda: objective)
    detached(N2 / 'analyze_targeted_results_v01.py', {'tokenize', 'strict_rule', 'gold_coordinates', 'validate_objective_trace'}, retained)
    return own, retained['validate_objective_trace']


def schedule(rows):
    epoch = cursor = 0
    indices, ids = [], []
    for _ in range(32):
        order = list(range(168))
        random.Random(1729 + epoch).shuffle(order)
        batch = order[cursor:cursor + 12]
        indices.append(batch)
        ids.append([rows[i]['id'] for i in batch])
        cursor += len(batch)
        if cursor == 168:
            epoch, cursor = epoch + 1, 0
    return dict(batch_indices=indices, batch_ids=ids, batch_indices_sha256=digest(indices),
                final_progress=dict(epochs_completed=epoch, row_cursor=cursor, optimizer_steps=32))


def model_binding(summary, plan, report, policy, *, initial):
    return dict(checkpoint_sha256=summary['initial_checkpoint_sha256'] if initial else report['checkpoint_sha256'],
                model_state_sha256=report['initial_model_state_sha256'] if initial else report['final_model_state_sha256'],
                initial_continuation_checkpoint_sha256=summary['initial_continuation_checkpoint_sha256'],
                parent_base_sha256=SOURCE_PARENT_SHA, context_sha256=digest(plan['context_contract']), training_policy=policy,
                branch_digests=report['initial_branch_digests'] if initial else report['final_branch_digests'])


def validate_training(summary, report, plan, rows, checkpoint_pin, own, objective_validator):
    require(report['schema'] == 'bounded-split-feature-span-legal-formula-training/v1'
            and all(report.get(k) is v for k, v in FALSE.items()), 'New unqualified authoritative training report required')
    require(type(report['optimizer_steps']) is int and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
            and report['training_executed'] is True and report['stopped_reason'] == 'step_limit', 'Complete32 returned updates required')
    require(report['checkpoint_sha256'] == checkpoint_pin['sha256']
            and report['source_parent_checkpoint_sha256'] == SOURCE_PARENT_SHA
            and report['source_parent_model_state_sha256'] == SOURCE_MODEL_SHA
            and report['initial_model_state_sha256'] == report['training_call_initial_model_state_sha256']
            == summary['baseline_model_state_sha256'] == summary['initial_model_state_sha256']
            and report['initial_model_state_sha256'] != SOURCE_MODEL_SHA,
            'Opaque combined34/common original23 parent/current-call state bindings differ')
    require(report['previous_split_feature_checkpoint_sha256'] == summary['initial_checkpoint_sha256']
            and report['initial_continuation_checkpoint_sha256'] == summary['initial_continuation_checkpoint_sha256'],
            'Initial complete outer and immutable warm child bindings differ')
    for key in ('initial_checkpoint_sha256', 'initial_model_state_sha256', 'final_model_state_sha256', 'frozen_parameters_sha256_initial', 'frozen_parameters_sha256_final'):
        require(type(report[key]) is str and re.fullmatch(r'[0-9a-f]{64}', report[key]), 'Reported opaque fingerprint format differs')
    policy = own['_policy']('split-features'); partition = policy['parameter_partition']
    require(report['training_policy'] == policy and report['training_policy_sha256'] == digest(policy)
            and report['parameter_partition'] == summary['parameter_partition'] == partition
            and summary['final_model_state_sha256'] == report['final_model_state_sha256']
            and len(partition['model_parameter_names']) == 34 and len(partition['trainable_parameter_names']) == 17
            and len(partition['frozen_parameter_names']) == 17, 'Exact34/17/17 policy or state summary differs')
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
    initial_branches = report['initial_branch_digests']; final_branches = report['final_branch_digests']
    own['_validate_branch_pair'](initial_branches, final_branches)
    require(report['training_call_initial_branch_digests'] == initial_branches == summary['initial_branch_digests']
            and final_branches == summary['final_branch_digests']
            and initial_branches['modality_feature_state_sha256'] == initial_branches['span_feature_state_sha256']
            and initial_branches['modality_path_state_sha256'] == final_branches['modality_path_state_sha256'] == FROZEN17_SHA
            and report['frozen_parameters_sha256_initial'] == report['frozen_parameters_sha256_final'] == FROZEN17_SHA,
            'Normalized feature-copy initialization or frozen17 prior-parent anchor differs')
    previous = FROZEN17_SHA; previous_branch = initial_branches; occurrence_count = 0
    for entry, batch in zip(freeze['batches'], batches, strict=True):
        records = [rows[index] for index in batch['indices']]
        expected = own['_freeze_entry'](batch['optimizer_step'], batch['indices'], records, partition,
            entry['frozen_parameters_sha256_before'], entry['frozen_parameters_sha256_after'], entry['changed_parameter_names'],
            [r['modality_logits'] for r in entry['modality_before']], [r['modality_logits'] for r in entry['modality_after']],
            entry['branch_digests_before'], entry['branch_digests_after'])
        require(expected == entry and entry['frozen_parameters_sha256_before'] == previous
                and entry['branch_digests_before'] == previous_branch,
                'Completed freeze/source/modal/gradient/branch continuity differs')
        for left, right in zip(entry['modality_before'], entry['modality_after'], strict=True):
            require(score_bytes(dict(tokens=[], modality_logits=left['modality_logits']), ('modality_logits',))
                    == score_bytes(dict(tokens=[], modality_logits=right['modality_logits']), ('modality_logits',)),
                    'Training modality binary32 bytes differ, including signed zero')
        previous = entry['frozen_parameters_sha256_after']; previous_branch = entry['branch_digests_after']; occurrence_count += len(records)
    require(previous == FROZEN17_SHA and previous_branch == final_branches and occurrence_count == 384,
            'Frozen-state/normalized branch endpoint/384-occurrence chain differs')
    constant = report['modality_constant_trace']
    require(constant == own['_constant_summary'](constant['batches'], batches) and constant['completed_updates'] == 32,
            'Constant modality loss completed-batch trace differs')
    changed = report['changed_parameter_names']
    require(type(changed) is list and len(changed) == len(set(changed))
            and set(changed) <= set(partition['trainable_parameter_names']), 'Changed parameters violate split partition')
    tuning = report['tuning']
    require(type(tuning['rows_evaluated']) is int and 0 <= tuning['rows_evaluated'] <= 96
            and tuning['complete'] is (tuning['rows_evaluated'] == 96) and tuning['teacher_forcing'] is True
            and tuning['used_for_fit_or_selection'] is False and tuning['objective_policy_sha256'] == digest(policy['objective_policy'])
            and (tuning['objective_loss'] is None if tuning['rows_evaluated'] == 0 else type(tuning['objective_loss']) in (int, float)
                 and math.isfinite(tuning['objective_loss']) and tuning['objective_loss'] >= 0), 'Exposed tuning diagnostic differs')
    forward = report['forward_accounting']; measured = tuning['rows_evaluated']
    require(type(forward) is dict and set(forward) == {'schema', 'training_model_forward_calls', 'training_modality_encoder_calls',
            'training_span_encoder_calls', 'training_source_row_occurrences', 'tuning_model_forward_calls',
            'tuning_modality_encoder_calls', 'tuning_span_encoder_calls', 'tuning_source_row_occurrences',
            'restore_validation_and_external_evaluation_forwards_included'}
            and forward['schema'] == 'split-feature-training-forward-accounting/v1'
            and all(type(forward[key]) is int and forward[key] == 64 for key in
                    ('training_model_forward_calls', 'training_modality_encoder_calls', 'training_span_encoder_calls'))
            and forward['training_source_row_occurrences'] == 768 and forward['tuning_source_row_occurrences'] == measured
            and measured % 12 == 0
            and all(type(forward[key]) is int and forward[key] == measured // 12 for key in
                    ('tuning_model_forward_calls', 'tuning_modality_encoder_calls', 'tuning_span_encoder_calls'))
            and forward['restore_validation_and_external_evaluation_forwards_included'] is False,
            'Recorded two-feature-path training/tuning forward scope differs')
    return dict(policy=policy, policy_sha256=digest(policy), parameter_partition=partition,
                recorded_completed_updates=32, trace_sha256=digest(trace), final_progress=progress,
                objective_trace=objective, freeze_trace_sha256=digest(freeze), freeze_training_row_occurrences=384,
                constant_modality_trace_sha256=digest(constant), normalized_initial_branches=initial_branches,
                normalized_final_branches=final_branches, normalized_branch_tensor_custody_independently_attested=False,
                initial_model_state_sha256=report['initial_model_state_sha256'], final_model_state_sha256=report['final_model_state_sha256'],
                frozen_parameters_sha256=previous, frozen_tensor_custody_independently_attested=False,
                checkpoint_opaque_raw_pin=checkpoint_pin, checkpoint_JSON_parsed=False,
                reported_optimizer_parameter_order=partition['optimizer_parameter_order'], optimizer_moments_independently_parsed=False,
                changed_parameter_names_reported=changed, tuning_objective_loss=tuning['objective_loss'], tuning_rows=measured,
                recorded_forward_accounting=forward, independent_numerical_forward_replay_performed=False)


def raw_projection(raw):
    return [dict(scores=row['scores'], raw={key: result.get(key) for key in
            ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')})
            for row, result in zip(raw['occurrences'], raw['inference']['rows'], strict=True)]


def compare_actual_modalities(baseline, trained, populations, receipt, cell):
    require(receipt['schema'] == 'split-feature-modality-score-comparison/v1' and receipt['cell'] == cell
            and receipt['total_source_rows'] == receipt['bit_equal_count'] == 392 and receipt['exact_modal_score_retention_required'] is True
            and receipt['full_IR_retention_implied'] is False and receipt['semantic_accuracy'] is None
            and all(receipt.get(k) is v for k, v in FALSE.items()), 'Saved modality-retention receipt scope differs')
    expected = []; vectors = bytearray()
    for name in PANELS:
        records = []
        for source, left, right in zip(populations[name], baseline[name]['occurrences'], trained[name]['occurrences'], strict=True):
            sha = hashlib.sha256(source['source_text'].encode()).hexdigest()
            require(left['id'] == right['id'] == source['id'] and left['source_sha256'] == right['source_sha256'] == sha,
                    'Complete modality occurrence source join differs')
            a, b = score_bytes(left['scores'], ('modality_logits',)), score_bytes(right['scores'], ('modality_logits',))
            require(a == b, 'Actual trained modality bytes changed, including signed zero')
            vectors.extend(a)
            records.append(dict(id=source['id'], source_sha256=sha, parent_f32_sha256=hashlib.sha256(a).hexdigest(),
                                trained_f32_sha256=hashlib.sha256(b).hexdigest(), bit_equal=True))
        expected.append(dict(name=name, rows=records, equal_count=len(records), count=len(records)))
    require(receipt['panels'] == expected, 'Saved modality receipt differs from complete independent source replay')
    return dict(source_rows=392, binary32_scalars=1176, bit_equal_count=392,
                ordered_parent_and_trained_modality_sha256=hashlib.sha256(vectors).hexdigest(),
                includes_abstentions_and_law=True, saved_receipt_independently_recomputed=True, full_IR_retention_implied=False)


def qualified_prior():
    """Pin the complete retained87 output set before any reference access."""
    freeze = read(N3 / 'two-cell-output-freeze-v01.json')
    analysis = read(N3 / 'permission-retention-result-analysis-v01.json')
    review = read(N3 / 'result-independent-review-v01.json')
    runtime = read(N3 / 'runtime-independent-review-v01.json')
    final = read(N3 / 'final-permission-retention-integration-independent-review-v01.json')
    hybrid = read(HYBRID_OUTPUT)
    hybrid_approval = read(M / 'saved-score-hybrid-source-independent-review-v02.json')
    for value in (analysis, review, runtime, final, hybrid):
        require(value['passed'] is True and value['findings'] == [], 'Clean prior result/runtime/integration/hybrid required')
    require(hybrid['schema'] == 'saved-score-hybrid-exposed-diagnostic/v1'
            and hybrid['analyzer'] == dict(path=str(HYBRID_SOURCE), **EXPECTED[str(HYBRID_SOURCE)])
            and hybrid['independent_source_review'] == dict(path=str(M / 'saved-score-hybrid-source-independent-review-v02.json'),
                **EXPECTED[str(M / 'saved-score-hybrid-source-independent-review-v02.json')])
            and hybrid_approval['passed'] is True and hybrid_approval['findings'] == []
            and hybrid_approval['analyzer'] == hybrid['analyzer']
            and hybrid['candidate_selected'] is None and hybrid['trained_hybrid_model'] is False
            and hybrid['actual_model_forwards'] == hybrid['optimizer_updates'] == hybrid['checkpoint_JSON_parses'] == 0
            and hybrid['all_existing_N3_panels_reproduced_exactly'] is True,
            'Exact qualified post-hoc diagnostic source/scope differs')
    require(freeze['schema'] == 'permission-retention-two-cell-freeze/v1' and freeze['all_two_outputs_frozen'] is True
            and freeze['authorizes_authored_eval_scoring'] is True and freeze['new_pair_outputs_scored_before_freeze'] is False
            and freeze['reference_packet_previously_scored'] is True and freeze['independent_blinding'] is False,
            'Previously exposed frozen N3 pair required')
    require(runtime['total_actual_returned_optimizer_updates'] == 64 and runtime['result_file_count'] == 87
            and runtime['all_original526_record_bodies_unchanged'] is True
            and final['actual_publications']['source']['actual_merge'] == 'b95938c2a816075466f8dc84f339cf622414030d'
            and final['actual_publications']['root']['actual_merge'] == '203f482ddb691f2196a27c5c17b99a00c17bdeeb',
            'Qualified retained execution/publication differs')
    for path in (N3 / 'permission-retention-result-analysis-v01.json', N3 / 'result-independent-review-v01.json', N3 / 'runtime-independent-review-v01.json'):
        require(final['artifacts'][str(path)] == EXPECTED[str(path)], 'Final integration raw binding differs')
    require([entry['cell']['id'] for entry in freeze['cells']] == ['all-parameters', 'span-heads-only'], 'Exact retained cells required')
    saved, infos = {}, {}
    for entry in freeze['cells']:
        for path, expected in entry['results'].items():
            require(path not in saved and analysis['saved_output_pins'][path] == runtime['artifacts'][path]
                    == review['artifacts'][path] == hybrid['artifacts'][path] == expected, 'Retained raw result/review/hybrid joins differ')
            register(dict(path=path, **expected)); saved[path] = expected
        root = Path(entry['summary']['path']).parent
        require(inventory(root) == entry['results'], 'Complete retained result inventory differs')
        summary = read(Path(register(entry['summary'])['path']))
        plan = read(Path(register(entry['plan'])['path']))
        report = read(Path(register(summary['training'])['path']))
        infos[entry['cell']['id']] = dict(entry=entry, summary=summary, plan=plan, report=report, root=root)
    require(len(saved) == 87, 'All87 retained outputs required')
    registration = read(Path(register(freeze['registration'])['path']))
    require(registration['schema'] == 'permission-retention-curriculum-registration/v1' and len(registration['source_owner_pins']) == 32,
            'Retained source/context closure differs')
    for descriptor in registration['source_owner_pins'].values(): register(descriptor)
    return dict(freeze=freeze, analysis=analysis, hybrid=hybrid, infos=infos, saved=saved, registration=registration)


def validate_loaded_owners(opening, closing, declared):
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    required = {prefix + name for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss', 'legal_span_split_features')}
    required |= {'ipfs_datasets_py.logic.legal_ir.joint_span_selection',
                 'ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture'}
    require(type(opening) is dict and type(closing) is dict and type(declared) is dict
            and opening == closing and required <= set(opening) <= set(declared)
            and all(descriptor == declared[name] for name, descriptor in opening.items()),
            'Reported loaded producers must include all six required owners with unchanged approved origins')
    return dict(reported_loaded_owner_count=len(opening), declared_raw_source_count=len(declared),
                required_loaded_owners=sorted(required), opening_closing_reported_maps_equal=True,
                independent_import_origin_replay_performed=False)


def validate_new_envelope(freeze):
    require(type(freeze) is dict and freeze['schema'] == 'split-feature-output-freeze/v1'
            and freeze['all_outputs_frozen'] is True and freeze['authorizes_authored_eval_scoring'] is True
            and freeze['new_trained_outputs_scored_before_freeze'] is False and freeze['reference_packet_previously_scored'] is True
            and freeze['independent_blinding'] is False and freeze['reference_builder_author_visible'] is True,
            'Frozen exposed new single-cell envelope required')
    require(freeze['runner'] == dict(path=str(RUNNER), **EXPECTED[str(RUNNER)]), 'Exact registered runner required')
    require(type(freeze['cells']) is list and len(freeze['cells']) == 1, 'One registered candidate only')
    entry = freeze['cells'][0]
    require(set(entry) == {'cell', 'plan', 'summary', 'guardian_terminal', 'pre_admission', 'results'}
            and entry['cell'] == dict(id='split-features', trainable_parameter_policy='split-features',
                actor_ranking_enabled=False, presence_ce_weight=1, modality_loss_weight=2), 'Closed fixed split-feature cell required')
    root = Path(entry['summary']['path']).parent
    require(root == Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/split-feature-20261013-split-features-01/results')
            and set(entry['results']) == expected_result_paths(root) and len(entry['results']) == 53, 'Exact owned53 result paths required')
    saved = {}
    for path, expected in entry['results'].items():
        register(dict(path=path, **expected)); saved[path] = expected
    require(inventory(root) == saved, 'Complete frozen53 output inventory differs')
    terminal = read(Path(register(entry['guardian_terminal'], root.parent / 'guardian-exit.json')['path']))
    require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
            and terminal['returncode'] == terminal['child_returncode'] == 0
            and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
            'Successful durable released guardian required')
    register(entry['pre_admission'], root.parent / 'pre-admission.json')
    summary = read(Path(register(entry['summary'], root / 'summary.json')['path']))
    plan = read(Path(register(entry['plan'], M / 'split-features-plan-v01.json')['path']))
    registration = read(Path(register(freeze['registration'], M / 'registration-v01.json')['path']))
    data = read(Path(register(freeze['training_export'], M / 'training-export-v01.json')['path']))
    require(registration['schema'] == 'split-feature-curriculum-registration/v1' and len(registration['source_owner_pins']) == 33
            and registration['data_export'] == freeze['training_export'] == plan['data_export']
            and data['schema'] == 'targeted-loss-curriculum-export/v1' and data['semantic_gold'] is False
            and pair(freeze['training_export']) == dict(bytes=5052701, sha256='a75b4125078d81aafabe1dcbe0e704da7386d859a019c158aef7ef1f7bb71f62')
            and registration['previously_exposed_authored_evaluation'] is True
            and registration['independent_semantic_holdout'] is False and registration['reference_packet_child_access'] is False,
            'Byte-identical exposed data/context registration required')
    for descriptor in registration['source_owner_pins'].values(): register(descriptor)
    for path, expected in plan['artifacts'].items(): register(dict(path=path, **expected))
    runner = dict(globals(), F=M, __file__=str(RUNNER), SCHEMA='split-feature-cell-plan/v1',
                  PLAN_FIELDS=source_constants(RUNNER, {'PLAN_FIELDS'})['PLAN_FIELDS'],
                  RETAINED_FORBIDDEN=source_constants(RUNNER, {'RETAINED_FORBIDDEN'})['RETAINED_FORBIDDEN'])
    detached(RUNNER, {'validate_plan'}, runner); runner['validate_plan'](plan)
    require(plan['cell'] == entry['cell'] == summary['cell'] and plan['source_owner_pins'] == registration['source_owner_pins']
            and plan['context_contract'] == registration['context_contract'] and plan['parent_capture_reference'] == registration['parent_capture_reference']
            and plan['parent_model_state_sha256'] == SOURCE_MODEL_SHA and plan['parent_base_canonical_sha256'] == SOURCE_PARENT_SHA
            and plan['training_manifest_sha256'] == digest(data['training_populations']['mixed'])
            == 'afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34', 'Registered parent/context/training168 differs')
    require(summary['schema'] == 'split-feature-cell-results/v1' and summary['status'] == 'completed'
            and summary['actual_new_updates'] == 32 and summary['training_count'] == 168
            and summary['same_original_parent_model_sha256'] == SOURCE_MODEL_SHA and summary['parent_optimizer_steps'] == 400
            and summary['baseline_optimizer_steps'] == 0 and summary['baseline_reuse'] is None
            and summary['fresh_Adam'] is True and summary['inherited_optimizer_moments'] is False
            and summary['configured_dimension'] == 384 and summary['latent_enabled'] is False
            and summary['actual_encoder_calls'] == 0 and summary['actual_encoder_calls_scope'] == 'external_latent_or_context_encoders'
            and summary['feature_paths_per_source_model_forward'] == 2 and summary['equal_compute_budget_claimed'] is False
            and summary['original_artifacts_byte_exact'] is True and summary['semantic_accuracy'] is None
            and summary['independent_statutory_gold'] is False and summary['checkpoint_selection_executed'] is False
            and summary['default_promotion'] is False and summary['Lake_executed'] is False
            and summary['promotion_gate'] == plan['promotion_gate'] and all(summary.get(k) is v for k, v in FALSE.items()),
            'Completed source-only32 fresh-subset-Adam summary scope differs')
    loaded_owners = validate_loaded_owners(summary['opening_owners'], summary['closing_owners'], registration['source_owner_pins'])
    checkpoint = register(summary['checkpoint'], root / 'cell-checkpoint.json')
    report_descriptor = register(summary['training'], root / 'cell-training.json')
    require(pair(checkpoint) == saved[checkpoint['path']] and pair(report_descriptor) == saved[report_descriptor['path']],
            'Opaque checkpoint or report outside frozen bundle')
    report = read(Path(report_descriptor['path']))
    schedule_path = root / 'data-schedule-before-models.json'
    prepared = read(schedule_path)
    require(prepared['schedule'] == summary['prepared_schedule'] == schedule(data['training_populations']['mixed'])
            and prepared['training_count'] == 168 and prepared['model_imported'] is False
            and all(prepared.get(k) is v for k, v in FALSE.items()), 'Saved pre-model schedule differs')
    return dict(entry=entry, summary=summary, plan=plan, report=report, registration=registration,
                data=data, result_root=root, saved=saved, checkpoint_pin=checkpoint, loaded_owner_contract=loaded_owners)


def replay_retained(prior, populations, metadata, old_ns, greedy, joint, scorer):
    panels, compact, captures, descriptors = [], {}, {}, {}
    first = prior['infos']['all-parameters']
    require(prior['infos']['span-heads-only']['summary']['baseline_panels'] == first['summary']['baseline_panels'], 'One exact retained parent required')
    specs = [('baseline', first, first['summary']['baseline_panels'], True)]
    specs += [(name, prior['infos'][name], prior['infos'][name]['summary']['diagnostics'], False)
              for name in ('all-parameters', 'span-heads-only')]
    previous = {(r['state'], r['panel']): r for r in prior['analysis']['baseline_and_two_cell_panels']}
    for state, info, entries, initial in specs:
        require([r['name'] for r in entries] == list(PANELS), 'Complete retained panel order required')
        captures[state], descriptors[state] = {}, {}
        model = old_ns['model_binding'](info['summary'], info['plan'], info['report'], info['report']['training_policy'], initial=initial)
        for name, descriptor in zip(PANELS, entries, strict=True):
            panel, rows, raw, chosen = old_ns['analyze_panel'](state, name, descriptor, populations[name], metadata.get(name),
                model, greedy, joint, scorer, prior['saved'], info['root'])
            require(panel == previous[state, name], 'Retained scalar scoring replay differs from qualified prior')
            panels.append(panel); compact[state, name] = rows
            captures[state][name] = dict(raw=raw, selected=chosen); descriptors[state][name] = descriptor
    hybrid_ns = dict(globals())
    detached(HYBRID_SOURCE, {'compose', 'hybrid_panel'}, hybrid_ns)
    for name in PANELS:
        panel, rows, records, raw = hybrid_ns['hybrid_panel'](name, populations[name], metadata.get(name),
            captures['baseline'][name]['raw'], captures['all-parameters'][name]['raw'],
            descriptors['baseline'][name]['raw'], descriptors['all-parameters'][name]['raw'], joint, scorer, old_ns)
        require(records == prior['hybrid']['hybrid_occurrences'][name], 'Retained hybrid copied-score provenance or exact replay differs')
        panels.append(panel); compact['saved-score-hybrid', name] = rows
    require(panels == prior['hybrid']['state_and_panel_results'], 'Complete28 retained baseline/full/frozen/hybrid summaries differ')
    return panels, compact, captures, descriptors


def initial_parity_recount(info, captures, parent, parent_descriptors):
    summary, plan = info['summary'], info['plan']
    reference = plan['parent_capture_reference']
    require(reference['freeze'] == dict(path=str(N3 / 'two-cell-output-freeze-v01.json'), **EXPECTED[str(N3 / 'two-cell-output-freeze-v01.json')])
            and reference['summary'] == dict(path=str(parent['entry']['summary']['path']), **pair(parent['entry']['summary']))
            and reference['panels'] == {name: parent_descriptors[name]['raw'] for name in PANELS},
            'Qualified full parent source capture reference map differs')
    panels = []; head_bytes = bytearray()
    for name, fresh in zip(PANELS, summary['baseline_panels'], strict=True):
        old = parent['summary']['baseline_panels'][list(PANELS).index(name)]
        left = read(Path(register(old['raw'])['path']))
        right = captures[name]['raw']
        require(raw_projection(left) == raw_projection(right), 'Initial complete source/head/greedy row projection differs from parent')
        require(captures[name]['selected']['rows'] == read(Path(register(old['joint'])['path']))['rows'],
                'Initial complete joint decisions differ from qualified parent')
        for a, b in zip(left['occurrences'], right['occurrences'], strict=True):
            fields = ('modality_logits', 'presence_logits', 'start_logits', 'end_logits')
            require(a['id'] == b['id'] and a['source_sha256'] == b['source_sha256']
                    and canonical(a['scores']) == canonical(b['scores']) and score_bytes(a['scores'], fields) == score_bytes(b['scores'], fields),
                    'Initial full-head tokens/binary32/source-ID/hash differs')
            head_bytes.extend(score_bytes(b['scores'], fields))
        panels.append(dict(name=name, count=len(left['occurrences']), parent_capture=reference['panels'][name], fresh_capture=fresh['raw'],
            complete_score_payloads_sha256=digest([row['scores'] for row in left['occurrences']]), all_four_heads_and_tokens_exact=True))
    expected = dict(schema='split-feature-initial-parent-head-parity/v1', checked_before_training=True,
        total_source_rows=392, all_four_heads_and_tokens_exact=True, parent_reference=reference, panels=panels,
        model_forward_calls_added=0, **FALSE)
    require(summary['initial_parent_head_parity'] == expected, 'Inline initial392 parity receipt differs from independent replay')
    return dict(source_rows=392, initial_all_four_heads_tokens_greedy_joint_equal_parent=True,
                ordered_all_four_head_binary32_sha256=hashlib.sha256(head_bytes).hexdigest(),
                inline_saved_receipt_independently_recomputed=True, checkpoint_combined34_parent23_hash_equality_required=False,
                actual_additional_model_forwards=0)


def promotion_observation(panel):
    permission = panel['modalities']['permission_counts']
    return dict(raw_exact_IR=panel['raw_exact_IR'], joint_exact_IR=panel['joint_exact_IR'], permission_counts=permission,
        exposed_old96_gate_met=panel['raw_exact_IR'] == panel['joint_exact_IR'] == 96
            and permission['raw_decoded']['P_to_O'] == permission['joint_decoded']['P_to_O'] == 0,
        necessary_engineering_gate_only=True, model_selection_performed=False)


def main():
    global PACKET_ALLOWED, WRITES_ALLOWED
    require(not OUTPUT.exists(), 'Exclusive new analysis output required')
    own = pin(Path(__file__).resolve()); EXPECTED[own['path']] = pair(own)
    approval_pin = pin(APPROVAL); EXPECTED[str(APPROVAL)] = pair(approval_pin)
    approval = read(APPROVAL)
    require(approval['schema'] == 'split-feature-analyzer-source-independent-review/v1' and approval['passed'] is True
            and approval['findings'] == [] and approval['analyzer'] == own, 'Exact clean independent analyzer approval required')
    for path in list(EXPECTED): pin(Path(path))
    freezer_review = read(M / 'terminal-copy-freeze-source-independent-review-v02.json')
    require(freezer_review['schema'] == 'split-feature-terminal-helper-source-independent-review/v1'
            and freezer_review['status'] == 'PASS' and freezer_review['findings'] == []
            and freezer_review['parsed_summary_inventory_join'] is True
            and freezer_review['producer_export_approved_identity_joins'] is True
            and freezer_review['artifacts'][str(FREEZER)] == dict(path=str(FREEZER), **EXPECTED[str(FREEZER)])
            and freezer_review['artifacts'][str(RUNNER)] == dict(path=str(RUNNER), **EXPECTED[str(RUNNER)]),
            'Actual repaired freezer source and clean custody qualification required')
    for path, descriptor in freezer_review['artifacts'].items(): register(descriptor, Path(path))
    contract = read(M / 'split-feature-evaluation-contract-v01.json')
    require(contract['initial_parity']['expected_initial_frozen17_state_sha256'] == FROZEN17_SHA
            and contract['parameter_geometry']['combined34_state_hash_is_not_original23_parent_hash'] is True,
            'Preregistered evaluation geometry differs')
    prior = qualified_prior()
    freeze_path = M / 'split-feature-output-freeze-v01.json'
    freeze_pin = pin(freeze_path); EXPECTED[str(freeze_path)] = pair(freeze_pin)
    freeze = read(freeze_path)
    info = validate_new_envelope(freeze)
    registration, data = info['registration'], info['data']
    old_registration = prior['registration']
    require(registration['context_contract'] == old_registration['context_contract']
            and registration['training_manifests'] == old_registration['training_manifests']
            and registration['reference_packet'] == freeze['reference_packet'] == prior['freeze']['reference_packet'],
            'Common context/training/reference contract differs')
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    require(set(registration['source_owner_pins']) == set(old_registration['source_owner_pins']) | {prefix + 'legal_span_split_features'},
            'Only new split source owner may extend exact retained32')
    for name, descriptor in old_registration['source_owner_pins'].items():
        new = registration['source_owner_pins'][name]
        require(pair(new) == pair(descriptor) and Path(new['path']) == M / 'datasets' / Path(descriptor['path']).relative_to(N3 / 'datasets'),
                'Retained source raw bytes or copied origin differs')
    old_ns = dict(globals())
    detached(N3 / 'analyze_permission_retention_v01.py',
        {'f32', 'modality_bytes', 'modality_choice', 'modality_summary', 'validate_capture', 'analyze_panel', 'model_binding'}, old_ns)
    for name in ('f32', 'modality_bytes', 'modality_choice', 'modality_summary'): globals()[name] = old_ns[name]
    n2_ns = dict(globals())
    detached(N2 / 'analyze_targeted_results_v01.py', {'tokenize', 'strict_rule', 'scorers'}, n2_ns)
    globals()['tokenize'] = n2_ns['tokenize']
    greedy, joint, scorer = n2_ns['scorers'](registration['source_owner_pins'])
    own_policy, objective_validator = policy_predicates(registration['source_owner_pins'])
    info['contract'] = validate_training(info['summary'], info['report'], info['plan'], data['training_populations']['mixed'],
        info['checkpoint_pin'], own_policy, objective_validator)
    expected_geometry = contract['parameter_geometry']
    for name in ('model_parameter_names', 'trainable_parameter_names', 'frozen_parameter_names', 'optimizer_parameter_order'):
        require(info['contract']['parameter_partition'][name] == expected_geometry[name], 'Preregistered exact parameter names/order differ')
    parity_occurrences = validate_parity(info, data['diagnostic_populations']['fresh_tune'], greedy, joint, info['saved'])
    require(parity_occurrences == 16, 'Initial/trained four two-row controls required')
    require(freeze['reference_packet'] == dict(path=str(PACKET), bytes=8262146,
        sha256='b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e'), 'Exact exposed reference descriptor required')
    for path in list(OBSERVED): pin(Path(path))
    PACKET_ALLOWED = True
    register(freeze['reference_packet'], PACKET)
    packet = read(PACKET)
    require(packet['geometry_review_packet']['semantic_gold'] is False
            and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
            and packet['split_contract']['shared_authored_templates'] is True
            and packet['split_contract']['statutory_provision_holdout'] is False
            and all(value is False for value in packet['authority'].values()), 'Exposed authored reference scope differs')
    populations = deepcopy(data['diagnostic_populations']); metadata = deepcopy(data['diagnostic_metadata'])
    populations['authored_eval'] = [row['model_example'] for row in packet['geometry_review_packet']['authored_eval']]
    metadata['authored_eval'] = [{key: row[key] for key in ('id', 'class_name', 'group_id', 'pair_id', 'pair_variant')}
                               for row in packet['geometry_review_packet']['authored_eval']]
    require([{key: row[key] for key in ('id', 'source_text', 'latent')} for row in populations['authored_eval']]
            == data['diagnostic_populations']['authored_eval'] and packet['diagnostic_populations'] == data['diagnostic_populations'],
            'Authored targets/source export joins differ')
    require(set(populations) == set(PANELS) and all(len(populations[name]) == COUNTS[name]
            and len({row['id'] for row in populations[name]}) == COUNTS[name] for name in PANELS)
            and sum(COUNTS.values()) == 392, 'Exact complete seven-panel source coverage required')
    panels, compact, retained_captures, retained_descriptors = replay_retained(prior, populations, metadata, old_ns, greedy, joint, scorer)
    current_captures = {}
    for state, initial, entries in [('split-baseline', True, info['summary']['baseline_panels']), ('split-features', False, info['summary']['diagnostics'])]:
        require([r['name'] for r in entries] == list(PANELS), 'Fresh baseline/trained complete source panel order required')
        current_captures[state] = {}
        for name, descriptor in zip(PANELS, entries, strict=True):
            model = model_binding(info['summary'], info['plan'], info['report'], info['contract']['policy'], initial=initial)
            internal_state = 'baseline' if initial else state
            panel, rows, raw, selected = analyze_panel(internal_state, name, descriptor, populations[name], metadata.get(name),
                model, greedy, joint, scorer, info['saved'], info['result_root'])
            panel['state'] = state; panels.append(panel); compact[state, name] = rows
            current_captures[state][name] = dict(raw=raw, selected=selected)
            for occurrence in raw['occurrences']:
                score_bytes(occurrence['scores'], ('modality_logits', 'presence_logits', 'start_logits', 'end_logits'))
    initial_recount = initial_parity_recount(info, current_captures['split-baseline'], prior['infos']['all-parameters'], retained_descriptors['baseline'])
    for name in PANELS:
        before = next(r for r in panels if r['state'] == 'baseline' and r['panel'] == name)
        after = next(r for r in panels if r['state'] == 'split-baseline' and r['panel'] == name)
        require({k:v for k,v in before.items() if k != 'state'} == {k:v for k,v in after.items() if k != 'state'},
                'Initial full metric/head/confusion decisions differ from parent')
    modal_descriptor = register(info['summary']['modality_retention'], info['result_root'] / 'trained-modality-retention.json')
    require(pair(modal_descriptor) == info['saved'][modal_descriptor['path']], 'Modal receipt outside frozen53')
    modalities = compare_actual_modalities({n:current_captures['split-baseline'][n]['raw'] for n in PANELS},
        {n:current_captures['split-features'][n]['raw'] for n in PANELS}, populations, read(Path(modal_descriptor['path'])), info['plan']['cell'])
    matched = []
    for state in ('baseline', 'all-parameters', 'span-heads-only', 'saved-score-hybrid'):
        for name in PANELS[:-1]:
            matched.append(dict(reference_state=state, current_state='split-features', panel=name,
                differences=differences(compact[state, name], compact['split-features', name])))
    gates = {state:promotion_observation(next(r for r in panels if r['state'] == state and r['panel'] == 'old_tune'))
             for state in ('baseline', 'all-parameters', 'span-heads-only', 'saved-score-hybrid', 'split-baseline', 'split-features')}
    require(inventory(info['result_root']) == info['saved'], 'Closing exact53 output inventory differs')
    for entry in prior['freeze']['cells']:
        require(inventory(Path(entry['summary']['path']).parent) == entry['results'], 'Closing exact retained87 inventories differ')
    for path in list(OBSERVED): pin(Path(path))
    require(pin(Path(__file__).resolve()) == own and pin(APPROVAL) == approval_pin, 'Closing analyzer/approval drift')
    result = dict(schema='split-feature-exposed-result-analysis/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), analyzer=own, independent_source_review=approval_pin,
        scope='One predeclared split-feature training run; pure saved-output and reported-trace recount, using previously exposed authored targets',
        state_and_panel_results=panels, matched_recoveries_and_regressions=matched, exposed_old96_gate_observations=gates,
        training_metadata_contract=info['contract'], reported_loaded_producers=info['loaded_owner_contract'], initial_parent_head_parity=initial_recount, trained_modality_retention=modalities,
        saved_output_pins=info['saved'], saved_output_count=53, retained_output_count=87,
        retained_parent_full_frozen_and_hybrid_summaries_reproduced_exactly=True,
        source_occurrences_per_state=392, authored_targets_per_state=384, unscored_law_sources_per_state=8,
        dormant_placeholder_controls=dict(stages=2, controls_per_stage=4, rows_per_control=2, occurrences=parity_occurrences,
            genuine_latent_semantics_tested=False, actual_latent_encoder_calls=0),
        recorded_actual_new_optimizer_updates=32, optimizer_updates_performed_by_analyzer=0,
        actual_model_forwards_performed_by_analyzer=0, checkpoint_JSON_parses=0,
        configured_dimension=384, latent_enabled=False, external_latent_encoder_calls=0,
        feature_paths_per_source_model_forward=2, equal_compute_budget_claimed=False,
        new_trained_reference_scoring_after_all53_outputs_frozen=True, reference_packet_previously_exposed=True,
        shared_authored_templates=True, independent_blinding=False, independent_statutory_gold=False,
        semantic_accuracy=None, statistical_significance_claimed=False,
        candidate_selected=None, default_promotion=False, trained_hybrid_model=False,
        full_arm_or_hybrid_training_reproduction_expected=False,
        genuine_8D_384D_768D_semantics_qualified=False, broader_logic_families_qualified=False, Lake_executed=False,
        reviewer_actions=dict(numerical_imports=0, subprocesses=0, remote_requests=0, resource_API_calls=0,
            Git_mutations=0, full_private_bodies_accessed=False, numerical_tensor_replay=False),
        limitations=['All384 targets were exposed previously and share authored templates. Law8 remains unreviewed and unscored; these counts are not independent statutory accuracy.',
            'Exact parent modality retention preserves existing modality errors. It does not guarantee full logical-rule retention; decoded abstentions are counted separately from head choices.',
            'The split span feature branch has no modality-CE gradient, so neither prior full-arm weights nor post-hoc hybrid spans are a required training control. No trained hybrid checkpoint exists.',
            'Trace/state/gradient/optimizer facts are source-bound trainer-reported metadata, not independent numerical tensor or optimizer-moment replay. The checkpoint remains opaque.',
            'This is one order/initialization seed and32 updates. Each source forward traverses two feature paths; equal compute is not claimed. No automatic checkpoint choice, default promotion, broader-family validation or Lake build is performed.'],
        artifacts=deepcopy(OBSERVED))
    WRITES_ALLOWED = True
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True, output=str(OUTPUT), bytes=OUTPUT.stat().st_size,
        sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), split_old96=gates['split-features']), sort_keys=True))


if __name__ == '__main__':
    main()

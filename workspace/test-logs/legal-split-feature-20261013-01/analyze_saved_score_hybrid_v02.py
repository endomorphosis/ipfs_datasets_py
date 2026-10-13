"""Post-hoc exposed saved-score recombination; never a new trained model.

Replay the three qualified N3 states, then combine the immutable parent's
modality with the full-update arm's presence/start/end scores. No model,
checkpoint parser, numerical package, compiler, remote or resource API is used.
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
OUTPUT = M / 'saved-score-hybrid-analysis-v01.json'
APPROVAL = M / 'saved-score-hybrid-source-independent-review-v02.json'
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
OBSERVED = {}
PACKET_ALLOWED = False
WRITES_ALLOWED = False
MAX_JSON_BYTES = 128 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'}:
        raise AssertionError('Saved-score diagnostic forbids numerical/production imports')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
        'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
        'os.mkdir', 'os.remove', 'os.rename', 'os.replace', 'os.rmdir', 'os.unlink'}:
        raise AssertionError('Saved-score diagnostic forbids process/network/resource/filesystem mutations')
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


def compose(parent, adapted, source, index, parent_capture, adapted_capture):
    """Copy only the registered components; retain exact original occurrence joins."""
    source_hash = hashlib.sha256(source['source_text'].encode()).hexdigest()
    require(parent['id'] == adapted['id'] == source['id']
            and parent['source_sha256'] == adapted['source_sha256'] == source_hash,
            'hybrid original occurrence ID/source joins differ')
    left, right = parent['scores'], adapted['scores']
    keys = {'schema', 'tokens', 'modality_logits', 'presence_logits', 'start_logits', 'end_logits'}
    require(set(left) == set(right) == keys and left['schema'] == right['schema'] == 'joint-source-span-scores/v1'
            and canonical(left['tokens']) == canonical(right['tokens']) == canonical(tokenize(source['source_text'])),
            'hybrid original schema/tokens/offset geometry differs')
    scores = deepcopy(right)
    scores['modality_logits'] = deepcopy(left['modality_logits'])
    components = (('modality', left, ('modality_logits',), parent_capture),
                  ('spans', right, ('presence_logits', 'start_logits', 'end_logits'), adapted_capture))
    provenance = {}
    for name, original, fields, capture in components:
        copied = {field: scores[field] for field in fields}
        expected = {field: original[field] for field in fields}
        require(canonical(copied) == canonical(expected) and score_bytes(scores, fields) == score_bytes(original, fields),
                'hybrid copied component differs from original logits')
        provenance[name] = dict(capture=deepcopy(capture), occurrence_index=index, id=source['id'], source_sha256=source_hash,
            original_full_scores_sha256=digest(original), original_tokens_sha256=digest(original['tokens']),
            copied_fields=list(fields), copied_component_sha256=digest(expected),
            copied_component_binary32_sha256=hashlib.sha256(score_bytes(original, fields)).hexdigest())
    return dict(id=source['id'], source_sha256=source_hash, scores=scores,
                provenance=dict(schema='saved-score-hybrid-occurrence-provenance/v1', components=provenance,
                    composed_scores_sha256=digest(scores), tokens_sha256=digest(scores['tokens']),
                    actual_model_forward=False, trained_model=False, model_checkpoint=None))


def hybrid_panel(name, rows, metadata, parent, adapted, parent_descriptor, adapted_descriptor, joint, scorer, old_ns):
    occurrences, raw_rows, selected_rows, records = [], [], [], []
    require(len(rows) == len(parent['occurrences']) == len(adapted['occurrences']) == COUNTS[name], 'complete hybrid panel coverage required')
    for index, (source, left, right) in enumerate(zip(rows, parent['occurrences'], adapted['occurrences'], strict=True)):
        occurrence = compose(left, right, source, index, parent_descriptor, adapted_descriptor)
        joint['_validated'](source['source_text'], occurrence['scores'])
        chosen = joint['select_joint_spans'](source['source_text'], occurrence['scores'], top_k=8, max_search_nodes=50000)
        raw = deepcopy(chosen['independent_greedy'])
        require(raw['actual_owner_report'] is False and raw['origin'] == 'reconstructed_independent_greedy_from_saved_scores',
                'hybrid greedy reconstruction must never become an actual owner report')
        raw['source_sha256'] = occurrence['source_sha256']
        occurrences.append({key: occurrence[key] for key in ('id', 'source_sha256', 'scores')})
        raw_rows.append(raw)
        selected_rows.append(dict(id=source['id'], result=chosen))
        records.append(dict(**occurrence, reconstructed_greedy=raw, joint=chosen))
    raw = dict(schema='saved-score-hybrid-reconstructed-panel/v1', actual_model_forwards=0,
               trained_model=False, actual_owner_report=False, occurrences=occurrences, inference=dict(rows=raw_rows))
    selected = dict(schema='saved-score-hybrid-joint-panel/v1', top_k=8, max_search_nodes=50000, rows=selected_rows)
    modalities = old_ns['modality_summary'](rows, raw, selected, metadata)
    if name == 'law':
        require(metadata is None and all('canonical_ir' not in row for row in rows) and modalities['reference_scored'] is False,
                'law8 must remain unreviewed and unscored')
        panel = dict(state='saved-score-hybrid', panel=name, rows=len(rows), raw_exact_IR=None, joint_exact_IR=None,
                     raw_decoded=sum(row['status'] == 'decoded' for row in raw_rows),
                     joint_selected=sum(row['result']['status'] == 'selected' for row in selected_rows), modalities=modalities,
                     reference_authority='previously_exposed_unreviewed_law_without_targets', semantic_accuracy=None)
        compact = {}
    else:
        score = scorer['score_panel'](rows, metadata, raw, selected_rows)
        compact = {row['id']: deepcopy(row) for row in score['rows']}
        for observation in modalities['row_observations']:
            compact[observation['id']]['observed_modalities'] = observation['observed_modalities']
            compact[observation['id']]['reference_modality'] = observation['reference_modality']
        panel = dict(state='saved-score-hybrid', panel=name, rows=len(rows), raw_exact_IR=score['raw_exact_ir'],
            joint_exact_IR=score['joint_exact_ir'], raw_exact_rate=score['raw_exact_ir']/len(rows),
            joint_exact_rate=score['joint_exact_ir']/len(rows), raw_abstentions=score['raw_abstentions'],
            joint_abstentions=sum(row['result']['status'] != 'selected' for row in selected_rows),
            modality_exact=score['modality_exact'], joint_modality_exact=score['joint_modality_exact'],
            role_exact_counts=score['role_exact_counts'], joint_role_exact_counts=score['joint_role_exact_counts'],
            temporal_presence_correct=score['temporal_presence_correct'], temporal_false_positives=score['temporal_false_positives'],
            temporal_false_negatives=score['temporal_false_negatives'], classes=score['classes'],
            pairwise_consistency=score['pairwise_consistency'], modalities=modalities,
            reference_authority='previously_exposed_authored_shared_template_engineering_evaluation',
            semantic_accuracy=None, pure_recomputed_score_sha256=digest(score), score_rows=score['rows'])
    return panel, compact, records, raw


def differences(parent, current):
    require(set(parent) == set(current), 'complete matched score identities required')
    return dict(raw_regressions=[key for key in parent if parent[key]['raw_exact_ir'] and not current[key]['raw_exact_ir']],
                raw_recoveries=[key for key in parent if not parent[key]['raw_exact_ir'] and current[key]['raw_exact_ir']],
                joint_regressions=[key for key in parent if parent[key]['joint_exact_ir'] and not current[key]['joint_exact_ir']],
                joint_recoveries=[key for key in parent if not parent[key]['joint_exact_ir'] and current[key]['joint_exact_ir']])


def main():
    global PACKET_ALLOWED, WRITES_ALLOWED
    require(not OUTPUT.exists(), 'exclusive new diagnostic output required')
    own = pin(Path(__file__).resolve())
    EXPECTED[own['path']] = pair(own)
    approval_pin = pin(APPROVAL)
    EXPECTED[str(APPROVAL)] = pair(approval_pin)
    approval = read(APPROVAL)
    require(approval['schema'] == 'saved-score-hybrid-source-independent-review/v1' and approval['passed'] is True
            and approval['findings'] == [] and approval['analyzer'] == own, 'exact clean independent analyzer source approval required')
    for path in list(EXPECTED):
        pin(Path(path))
    freeze = read(N3 / 'two-cell-output-freeze-v01.json')
    prior_analysis = read(N3 / 'permission-retention-result-analysis-v01.json')
    prior_result = read(N3 / 'result-independent-review-v01.json')
    runtime = read(N3 / 'runtime-independent-review-v01.json')
    final = read(N3 / 'final-permission-retention-integration-independent-review-v01.json')
    for value in (prior_analysis, prior_result, runtime, final):
        require(value['passed'] is True and value['findings'] == [], 'clean qualified N3 result/runtime/integration required')
    require(freeze['schema'] == 'permission-retention-two-cell-freeze/v1' and freeze['all_two_outputs_frozen'] is True
            and freeze['authorizes_authored_eval_scoring'] is True
            and freeze['new_pair_outputs_scored_before_freeze'] is False and freeze['reference_packet_previously_scored'] is True
            and freeze['independent_blinding'] is False and freeze['reference_builder_author_visible'] is True,
            'exact previously exposed frozen N3 pair required')
    require(runtime['total_actual_returned_optimizer_updates'] == 64 and runtime['result_file_count'] == 87
            and runtime['all_original526_record_bodies_unchanged'] is True
            and prior_result['reference_packet_previously_exposed'] is True and prior_result['default_promotion'] is False
            and final['actual_publications']['source']['actual_merge'] == 'b95938c2a816075466f8dc84f339cf622414030d'
            and final['actual_publications']['root']['actual_merge'] == '203f482ddb691f2196a27c5c17b99a00c17bdeeb',
            'qualified N3 execution/publication/exposure differs')
    for path in (N3 / 'permission-retention-result-analysis-v01.json', N3 / 'result-independent-review-v01.json', N3 / 'runtime-independent-review-v01.json'):
        require(final['artifacts'][str(path)] == EXPECTED[str(path)], 'final integration binding differs')
    saved = {}
    require(len(freeze['cells']) == 2 and [entry['cell']['id'] for entry in freeze['cells']] == ['all-parameters', 'span-heads-only'],
            'exact N3 two-cell ordering required')
    for entry in freeze['cells']:
        for path, expected in entry['results'].items():
            require(path not in saved and prior_analysis['saved_output_pins'][path] == runtime['artifacts'][path]
                    == prior_result['artifacts'][path] == expected, 'frozen result/independent review joins differ')
            register(dict(path=path, **expected))
            saved[path] = expected
        root = Path(entry['summary']['path']).parent
        require(inventory(root) == entry['results'], 'complete current N3 result inventory differs')
    require(len(saved) == 87, 'all87 N3 outputs must be preserved before diagnostic scoring')
    registration = read(Path(register(freeze['registration'])['path']))
    data = read(Path(register(freeze['training_export'])['path']))
    require(registration['schema'] == 'permission-retention-curriculum-registration/v1'
            and len(registration['source_owner_pins']) == 32 and data['schema'] == 'targeted-loss-curriculum-export/v1'
            and data['semantic_gold'] is False,
            'exact registered data/context/source closure differs')
    for value in registration['source_owner_pins'].values():
        register(value)
    require(freeze['reference_packet'] == dict(path=str(PACKET), bytes=8262146,
            sha256='b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e'),
            'exact previously exposed reference packet descriptor required')
    gap_path = N3 / 'datasets/docs/autoencoders/permission_retention_training_gaps_20261012.md'
    require('Separate modality and span representations.' in captured_bytes(gap_path, 10000).decode(), 'merged split-feature gap instruction missing')
    old_ns = dict(globals())
    detached(N3 / 'analyze_permission_retention_v01.py',
             {'f32', 'modality_bytes', 'modality_choice', 'modality_summary', 'validate_capture', 'analyze_panel', 'model_binding'}, old_ns)
    n2_ns = dict(globals(), f32=old_ns['f32'])
    detached(N2 / 'analyze_targeted_results_v01.py', {'tokenize', 'strict_rule', 'scorers'}, n2_ns)
    globals()['tokenize'] = n2_ns['tokenize']
    greedy, joint, scorer = n2_ns['scorers'](registration['source_owner_pins'])
    infos = {}
    for entry in freeze['cells']:
        identifier = entry['cell']['id']
        summary = read(Path(register(entry['summary'])['path']))
        plan = read(Path(register(entry['plan'])['path']))
        report = read(Path(register(summary['training'])['path']))
        require(summary['cell'] == plan['cell'] == entry['cell'] and summary['status'] == 'completed'
                and summary['actual_new_updates'] == 32 and summary['training_count'] == 168
                and summary['baseline_model_state_sha256'] == SOURCE_MODEL_SHA and summary['actual_encoder_calls'] == 0
                and summary['latent_enabled'] is False and plan['source_owner_pins'] == registration['source_owner_pins']
                and plan['context_contract'] == registration['context_contract'],
                'exact completed source-only N3 cell required')
        infos[identifier] = dict(entry=entry, summary=summary, plan=plan, report=report, root=Path(entry['summary']['path']).parent)
    first = infos['all-parameters']
    require(infos['span-heads-only']['summary']['baseline_panels'] == first['summary']['baseline_panels'], 'exact shared parent panels required')
    for path in list(OBSERVED):
        pin(Path(path))
    PACKET_ALLOWED = True
    register(freeze['reference_packet'], PACKET)
    packet = read(PACKET)
    require(packet['geometry_review_packet']['semantic_gold'] is False
            and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
            and packet['split_contract']['shared_authored_templates'] is True
            and packet['split_contract']['statutory_provision_holdout'] is False
            and all(value is False for value in packet['authority'].values()), 'exposed authored reference scope differs')
    populations = deepcopy(data['diagnostic_populations'])
    populations['authored_eval'] = [row['model_example'] for row in packet['geometry_review_packet']['authored_eval']]
    metadata = deepcopy(data['diagnostic_metadata'])
    metadata['authored_eval'] = [{key: row[key] for key in ('id', 'class_name', 'group_id', 'pair_id', 'pair_variant')}
                               for row in packet['geometry_review_packet']['authored_eval']]
    require([{key: row[key] for key in ('id', 'source_text', 'latent')} for row in populations['authored_eval']]
            == data['diagnostic_populations']['authored_eval'] and packet['diagnostic_populations'] == data['diagnostic_populations'],
            'authored target/source joins differ')
    panels, compact, captures, descriptors = [], {}, {}, {}
    state_specs = [('baseline', first, first['summary']['baseline_panels'], True)]
    state_specs.extend((identifier, infos[identifier], infos[identifier]['summary']['diagnostics'], False)
                       for identifier in ('all-parameters', 'span-heads-only'))
    previous_panels = {(row['state'], row['panel']): row for row in prior_analysis['baseline_and_two_cell_panels']}
    for state, info, entries, initial in state_specs:
        require([row['name'] for row in entries] == list(PANELS), 'all seven panels in exact source order required')
        captures[state], descriptors[state] = {}, {}
        model = old_ns['model_binding'](info['summary'], info['plan'], info['report'], info['report']['training_policy'], initial=initial)
        for name, descriptor in zip(PANELS, entries, strict=True):
            require(len(populations[name]) == COUNTS[name] and len({row['id'] for row in populations[name]}) == COUNTS[name],
                    'complete unique panel source occurrence IDs required')
            panel, rows, raw, selected = old_ns['analyze_panel'](state, name, descriptor, populations[name], metadata.get(name),
                model, greedy, joint, scorer, saved, info['root'])
            require(canonical(panel) == canonical(previous_panels[state, name]), 'retained state replay differs from qualified N3 analysis')
            for occurrence, actual, chosen in zip(raw['occurrences'], raw['inference']['rows'], selected['rows'], strict=True):
                reconstructed = chosen['result']['independent_greedy']
                require(all(canonical(reconstructed.get(key)) == canonical(actual.get(key)) for key in
                            ('status', 'reason', 'canonical_ir', 'minimum_decision_logit_margin')),
                        'unchanged reconstructed greedy decisions differ from actual saved owner output')
                score_bytes(occurrence['scores'], ('modality_logits', 'presence_logits', 'start_logits', 'end_logits'))
            panels.append(panel)
            compact[state, name] = rows
            captures[state][name], descriptors[state][name] = raw, descriptor
    hybrid_records, copied_modal_bytes, parent_modal_bytes = {}, bytearray(), bytearray()
    for name in PANELS:
        panel, rows, records, hybrid_raw = hybrid_panel(name, populations[name], metadata.get(name),
            captures['baseline'][name], captures['all-parameters'][name], descriptors['baseline'][name]['raw'],
            descriptors['all-parameters'][name]['raw'], joint, scorer, old_ns)
        panels.append(panel)
        compact['saved-score-hybrid', name] = rows
        hybrid_records[name] = records
        for parent, frozen, derived in zip(captures['baseline'][name]['occurrences'], captures['span-heads-only'][name]['occurrences'],
                                           hybrid_raw['occurrences'], strict=True):
            before = old_ns['modality_bytes'](parent['scores']['modality_logits'])
            require(before == old_ns['modality_bytes'](frozen['scores']['modality_logits'])
                    == old_ns['modality_bytes'](derived['scores']['modality_logits']), 'all392 frozen/hybrid modality vectors must equal parent bytes')
            parent_modal_bytes.extend(before)
            copied_modal_bytes.extend(old_ns['modality_bytes'](derived['scores']['modality_logits']))
    comparisons = []
    for state in ('baseline', 'all-parameters', 'span-heads-only'):
        for name in PANELS[:-1]:
            comparisons.append(dict(reference_state=state, panel=name, hybrid_relative_to_reference=differences(
                compact[state, name], compact['saved-score-hybrid', name])))
    old_gate = {}
    for state in ('baseline', 'all-parameters', 'span-heads-only', 'saved-score-hybrid'):
        panel = next(row for row in panels if row['state'] == state and row['panel'] == 'old_tune')
        permission = panel['modalities']['permission_counts']
        old_gate[state] = dict(raw_exact_IR=panel['raw_exact_IR'], joint_exact_IR=panel['joint_exact_IR'], permission_counts=permission,
            exposed_old96_gate_met=panel['raw_exact_IR'] == panel['joint_exact_IR'] == 96
                and permission['raw_decoded']['P_to_O'] == permission['joint_decoded']['P_to_O'] == 0,
            necessary_engineering_gate_only=True, model_selection_performed=False)
    for entry in freeze['cells']:
        require(inventory(Path(entry['summary']['path']).parent) == entry['results'], 'closing complete frozen inventory differs')
    for path in list(OBSERVED):
        pin(Path(path))
    require(pin(Path(__file__).resolve()) == own and pin(APPROVAL) == approval_pin, 'closing analyzer/source approval drift')
    result = dict(schema='saved-score-hybrid-exposed-diagnostic/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), analyzer=own, independent_source_review=approval_pin,
        scope='Post-hoc recombination of previously exposed saved scores; no new trained decoder and no selected checkpoint',
        composition_policy=dict(schema='saved-score-hybrid-composition-policy/v1', modality_state='baseline',
            span_state='all-parameters', copied_span_fields=['presence_logits', 'start_logits', 'end_logits'],
            source_tokens_from='all-parameters; required byte-identical to parent and exact source tokenizer',
            greedy_policy='unchanged retained reconstructed_independent_greedy_from_saved_scores',
            joint_top_k=8, joint_max_search_nodes=50000, target_based_modality_or_presence_override=False),
        state_and_panel_results=panels, hybrid_occurrences=hybrid_records, matched_recoveries_and_regressions=comparisons,
        exposed_old96_gate_observations=old_gate, all_existing_N3_panels_reproduced_exactly=True,
        modality_retention=dict(rows=392, scalars=1176, parent_hybrid_and_frozen_all_bit_equal=True,
            ordered_parent_binary32_sha256=hashlib.sha256(parent_modal_bytes).hexdigest(),
            ordered_hybrid_binary32_sha256=hashlib.sha256(copied_modal_bytes).hexdigest(), includes_abstained_and_law_rows=True),
        source_occurrences_per_state=392, authored_targets_per_state=384, unscored_law_sources_per_state=8,
        total_authored_scored_state_occurrences=1536, total_unscored_law_state_occurrences=32,
        reference_packet_previously_exposed=True, shared_authored_templates=True, independent_blinding=False,
        independent_statutory_gold=False, semantic_accuracy=None, statistical_significance_claimed=False,
        trained_hybrid_model=False, generated_model_checkpoint=None, candidate_selected=None, default_promotion=False,
        actual_model_forwards=0, optimizer_updates=0, checkpoint_JSON_parses=0, actual_encoder_calls=0,
        genuine_8D_384D_768D_semantics_qualified=False, broader_logic_families_qualified=False, Lake_executed=False,
        reviewer_actions=dict(numerical_imports=0, subprocesses=0, remote_requests=0, resource_API_calls=0,
                             Git_mutations=0, full_private_bodies_accessed=False),
        limitations=['The parent modality branch retains all of its existing head errors. Exact392 vector retention does not establish legal modality correctness.',
                     'This hybrid is a diagnostic assembled from two saved forward passes, not an executable split-feature model. Its result cannot be claimed as trained-model accuracy.',
                     'Every authored target was previously exposed and shares templates. Law8 is unreviewed and remains unscored. No independent statutory accuracy, seed robustness or model selection is established.',
                     'The actual split-feature trainer receives no modality-CE gradient in its trainable feature branch, so its learned spans need not reproduce the unrestricted arm or this saved-score hybrid.',
                     'Retained joint selection uses fixed topK8 and50000 nodes. Greedy reconstruction and typed single-rule structural stubs are unchanged engineering policies; no broader logic family or Lake compiler is run.'],
        artifacts=deepcopy(OBSERVED))
    WRITES_ALLOWED = True
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True, output=str(OUTPUT), bytes=OUTPUT.stat().st_size,
                         sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), old96=old_gate), sort_keys=True))


if __name__ == '__main__':
    main()

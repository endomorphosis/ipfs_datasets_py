#!/usr/bin/env python3
"""Independent saved-input, replay and scoring checks for owner-type stability.

The independent replay phase denies current fresh semantic files. Scoring
reconciles admitted metrics and selection before releasing those references.
Ownership types never authorize an owner anchor, attachment or formal output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import random
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metric
from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as candidates
from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_qualification as gates
from scripts.ops.legal_ir import qualify_legal_paired_ownership_head_v2 as prior
from scripts.ops.legal_ir import qualify_legal_temporal_placement_head as placement_prior
from scripts.ops.legal_ir import qualify_legal_temporal_ownership_head_v2 as old
from scripts.ops.legal_ir import run_legal_temporal_stability as runner
from scripts.ops.legal_ir import replay_legal_temporal_stability_teacher as teacher_checker

SCHEMA = 'legal-stability-owner-type-independent-qualification/v1'
ARMS = ('placement_ce', 'placement_kl', 'placement_head_only')
SEEDS = (1730, 1731)
STEPS = (0, 50, 100, 200)
CHECKPOINT_SCHEMA = 'legal-stability-temporal-owner-type-checkpoint/v1'
TRAIN = ('single_training', 'prior_paired_training', 'placement_training')
ADMITTED = (*TRAIN, *gates.PANELS)
PANELS = ('fresh_lexical', 'fresh_structural')
COUNTS = {'single_training':768, 'prior_paired_training':864, 'placement_training':864, **gates.PANEL_COUNTS, 'fresh_lexical':144, 'fresh_structural':144}
require = metric.require


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def expected_batch(single_groups, prior_units, placement_units, *, seed, step, arm):
    """Independent source-ID schedule; no IDs or labels enter model features."""
    require(type(seed) is int and seed in SEEDS and type(step) is int and 0 <= step < 200
            and arm in ARMS, 'bounded prospective batch identity required')
    for mapping, width in ((single_groups, 4), (prior_units, 12), (placement_units, 12)):
        require(type(mapping) is dict and len(mapping) >= 3 and
                all(type(k) is str and type(v) is list and len(v) == len(set(v)) == width
                    and all(type(i) is str for i in v) for k, v in mapping.items()), 'complete source-group mapping required')
        ids = [i for v in mapping.values() for i in v]
        require(len(ids) == len(set(ids)), 'sampler pools must partition source queries')
    def draw(mapping, salt, position, count):
        names = sorted(mapping); result = []
        for cursor in range(position, position + count):
            epoch, offset = divmod(cursor, len(names)); order = list(names)
            random.Random(salt + epoch).shuffle(order); result.append(order[offset])
        return result
    singles = draw(single_groups, seed, 3 * step, 3)
    use_placement = step % 2 == 1
    units = placement_units if use_placement else prior_units
    chosen = draw(units, seed + (2000003 if use_placement else 1000003), step // 2 if use_placement else step, 1)
    return {'single_group_ids': singles, 'prior_paired_unit_ids': [] if use_placement else chosen,
            'placement_unit_ids': chosen if use_placement else [],
            'query_ids': [i for name in singles for i in single_groups[name]] + units[chosen[0]]}


def evaluated_panels(step):
    require(type(step) is int and step in STEPS, 'prospective evaluation stage required')
    return ADMITTED if step in (0, 200) else gates.PANELS


def reference(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read_producer(pin):
    fields = {'path', 'bytes', 'sha256'}
    require(type(pin) is dict and (set(pin) == fields or set(pin) == fields | {'schema'}) and
            type(pin['path']) is str and Path(pin['path']).is_absolute() and
            type(pin['bytes']) is int and pin['bytes'] >= 0 and type(pin['sha256']) is str and
            re.fullmatch(r'[0-9a-f]{64}', pin['sha256']) is not None, 'closed type-strict byte reference required')
    require(wire(reference(pin['path'])) == wire({k: pin[k] for k in fields}), 'saved evidence bytes changed')
    if 'schema' in pin:
        require(pin['schema'] in (CHECKPOINT_SCHEMA, 'legal-paired-temporal-owner-type-checkpoint/v1') and
                json.loads(Path(pin['path']).read_bytes())['schema'] == pin['schema'], 'typed checkpoint schema differs')


def read(pin):
    read_producer(pin)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON member')
            result[key] = value
        return result
    return json.loads(Path(pin['path']).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False); handle.write('\n')
    return reference(path)


def phase_guard(manifest, sealed_keys):
    """Deny OS-level opens until the explicit checked release transition."""
    paths = {str(Path(manifest['artifacts'][key]['path']).resolve()) for key in sealed_keys}
    require(len(paths) == len(sealed_keys) == 4, 'four distinct fresh reference seals required')
    state = {'sealed_paths': sorted(paths), 'released': False, 'premature_read_attempts': [], 'postrelease_reads': []}
    def audit(event, args):
        if event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = str(Path(os.fsdecode(args[0])).resolve())
        if path in paths:
            if not state['released']:
                state['premature_read_attempts'].append(path)
                raise PermissionError('current fresh reference remains sealed: '+path)
            state['postrelease_reads'].append(path)
    sys.addaudithook(audit)
    return state


def independent_selection(scores):
    """Reconstruct the prospective gates from scored rows, not runner gates."""
    require(type(scores) is dict and all(type(k) is int for k in scores) and set(scores)==set(STEPS),
            'parent and all prospective stages required')
    checks={};ranks={}
    for step in STEPS:
        require(type(scores[step]) is dict and set(scores[step])==set(gates.PANELS),'exact nine admitted gate panels required')
        panels={}
        for panel in gates.PANELS:
            current,parent=scores[step][panel],scores[0][panel]
            require(type(current['count']) is int and current['count']==parent['count']==COUNTS[panel]
                    and len(current['rows'])==len(parent['rows'])==COUNTS[panel], 'full prospective panel denominator required')
            left={r['id']:r for r in parent['rows']};right={r['id']:r for r in current['rows']}
            require(len(left)==len(right)==COUNTS[panel] and set(left)==set(right),'complete identical source IDs required')
            require(all(wire({k:left[i][k] for k in ('id','source_sha256','proposed_time_span','target')})==
                        wire({k:right[i][k] for k in ('id','source_sha256','proposed_time_span','target')}) for i in left),
                    'source occurrence or target membership changed')
            failures=[];churn={};full=panel!=gates.NEW_TUNING
            for label in metric.CLASSES:
                ids={i for i,r in left.items() if r['target']==label}
                require(len(ids)==COUNTS[panel]//4,'balanced full class denominator required')
                bc={i for i in ids if left[i]['correct']};ac={i for i in ids if right[i]['correct']}
                ba={i for i in ids if left[i]['accepted_type_proposal'] and left[i]['correct']}
                aa={i for i in ids if right[i]['accepted_type_proposal'] and right[i]['correct']}
                be={i for i in ids if left[i]['accepted_type_error']};ae={i for i in ids if right[i]['accepted_type_error']}
                if len(ac)<len(bc):failures.append(label+':correct_below_parent')
                if full:
                    if len(ae)>len(be):failures.append(label+':accepted_errors_above_parent')
                    if ae-be:failures.append(label+':new_accepted_error_ids')
                    if len(aa)<len(ba):failures.append(label+':accepted_correct_below_parent')
                churn[label]={'fixed_ids':sorted(ac-bc),'lost_ids':sorted(bc-ac),'new_accepted_error_ids':sorted(ae-be)}
            panels[panel]={'eligible':not failures,'failures':failures,'class_churn':churn,
                          'accepted_correct_coverage_gate_applied':full,'zero_correctness_churn_required':False,**gates.FALSE}
        checks[str(step)]={'eligible':all(v['eligible'] for v in panels.values()),'panels':panels,**gates.FALSE}
        new=scores[step][gates.NEW_TUNING]
        require(type(new['macro_f1']) in (int,float) and math.isfinite(new['macro_f1']) and 0<=new['macro_f1']<=1
                and type(new['mean_nll']) in (int,float) and math.isfinite(new['mean_nll']) and new['mean_nll']>=0,
                'finite new-tuning ranking required')
        ranks[step]=(-new['macro_f1'],new['mean_nll'],step)
    eligible=[step for step in STEPS if checks[str(step)]['eligible']]
    require(0 in eligible,'explicit unchanged parent must remain eligible')
    return {'schema':gates.SELECTION_SCHEMA,'selected_steps':min(eligible,key=ranks.__getitem__),
            'eligible_steps':eligible,'ranking':{str(k):list(v) for k,v in ranks.items()},'eligibility':checks,
            'retention_panels':list(gates.RETENTION_PANELS),'ranking_panel':gates.NEW_TUNING,
            'accepted_correct_coverage_gate_applied':True,'zero_correctness_churn_required':False,**gates.FALSE}


def generation(value, checkpoint, sources_pin, sources, *, arm, seed, step, decoder_kind='stability_owner_type'):
    require(value['schema'] == 'legal-temporal-owner-type-source-generation/v1', 'generation schema differs')
    require(wire(value['model']) == wire({'checkpoint': checkpoint, 'decoder_kind': decoder_kind,
                                        'arm': arm, 'seed': seed, 'steps': step}),
            'generation model differs')
    require(wire(value['sources']) == wire(sources_pin), 'generation source binding differs')
    require(value['class_order'] == list(metric.CLASSES) and type(value['threshold']) is float and value['threshold'] == .8,
            'fixed taxonomy/threshold differs')
    require(all(value[key] is False for key in metric.FALSE_FIELDS | {'labels_supplied', 'source_id_used_as_feature', 'owner_or_cue_spans_supplied'}),
            'generation authority/input flags differ')
    require(value['source_text_conditioned'] is True and value['time_occurrence_conditioned'] is True,
            'occurrence conditioning required for every continuation arm')
    require(type(value['encoder_batch_forwards']) is int and value['encoder_batch_forwards'] == math.ceil(len(sources)/48) and
            type(value['encoder_source_evaluations']) is int and value['encoder_source_evaluations'] == len(sources),
            'generation actual counters differ')
    require(type(value['rows']) is list and len(value['rows']) == len(sources) and
            [r['id'] for r in value['rows']] == [s['id'] for s in sources], 'complete ordered source inventory required')
    for source, row in zip(sources, value['rows']): metric.checked_prediction(source, row)
    return value['rows']


def reconcile_metrics(actual, reported):
    old.reconcile_metrics(actual, reported)


def paired_comparison(baseline, treatment):
    before = {row['id']: row for row in baseline['rows']}
    require(len(before) == len(baseline['rows']) == len(treatment['rows']) and
            set(before) == {row['id'] for row in treatment['rows']}, 'paired metrics require identical complete query IDs')
    fixed = lost = 0
    for row in treatment['rows']:
        left = before[row['id']]
        require(all(wire(left[k]) == wire(row[k]) for k in ('source_sha256', 'proposed_time_span', 'target')),
                'paired source occurrence/reference binding differs')
        fixed += not left['correct'] and row['correct']; lost += left['correct'] and not row['correct']
    require(fixed-lost == treatment['correct']-baseline['correct'], 'paired correctness arithmetic differs')
    return {'count': len(before), 'correct_delta': fixed-lost, 'fixed': fixed, 'regressed': lost,
            'accepted_type_error_delta': treatment['accepted_type_errors']-baseline['accepted_type_errors']}


def producer_pins():
    paths = set(runner.producer_pins()) | set(candidates.producer_pins())
    paths.update(str(Path(m.__file__).resolve()) for m in (sys.modules[__name__], metric, corpus, old, prior, gates, placement_prior, teacher_checker))
    return [reference(path) for path in sorted(paths)]


def physical_metadata(slot):
    return {'arm': 'mixed_occurrences' if slot['decoder_kind'] == 'paired_owner_type' else slot['arm'],
            'seed': slot['seed'], 'step': 200 if slot['decoder_kind'] == 'paired_owner_type' else slot['additional_steps'],
            'decoder_kind': slot['decoder_kind']}


def load_inputs(freeze):
    config = read(freeze['config']); manifest = read(config['corpus_manifest'])
    guard = phase_guard(manifest, runner.SEALED_KEYS)
    runner.load_config(freeze['config']['path'])
    data = corpus.load_training_inputs(config['corpus_manifest']['path'])
    data = {**data, **data['retention_targets']}
    return data, guard


def verify_teacher_replay(freeze, data, config, initials, selection):
    """Rehash the prefit numerical receipt; never claim a second execution."""
    for value in (initials, selection):
        require(wire(value['teacher_cache_freeze']) == wire(freeze['teacher_cache_freeze']) and
                wire(value['independent_teacher_replay']) == wire(freeze['independent_teacher_replay']),
                'teacher freeze/replay lineage differs')
    cache_freeze = read(freeze['teacher_cache_freeze'])
    teacher_checker.verify_teacher_freeze(cache_freeze, freeze['config'], config)
    replayed = read(freeze['independent_teacher_replay'])
    require(replayed['schema'] == teacher_checker.SCHEMA and replayed['exact_replay'] is True and
            wire(replayed['config']) == wire(freeze['config']) and
            wire(replayed['teacher_cache_freeze']) == wire(freeze['teacher_cache_freeze']) and
            replayed['fresh_references_opened'] is False and replayed['fresh_reference_guard']['released'] is False and
            not replayed['fresh_reference_guard']['premature_read_attempts'] and
            not replayed['fresh_reference_guard']['postrelease_reads'], 'successful sealed prefit teacher replay required')
    require(type(replayed['encoder_batch_forwards']) is int and replayed['encoder_batch_forwards'] == 68 and
            type(replayed['encoder_source_evaluations']) is int and replayed['encoder_source_evaluations'] == 3264 and
            type(replayed['optimizer_updates']) is int and replayed['optimizer_updates'] == 0,
            'independent teacher work counters differ')
    require(wire(replayed['producer_files']) == wire(teacher_checker.producer_pins()), 'teacher replay producer closure changed')
    for pin in replayed['producer_files']: read_producer(pin)
    require(type(replayed['teachers']) is list and len(replayed['teachers']) == 2 and
            {row['seed'] for row in replayed['teachers']} == set(SEEDS), 'complete two-teacher replay required')
    projected = {name: [{key: row[key] for key in (*teacher_checker.SOURCE_KEYS, 'label', 'group_id')}
                        for row in data[name]] for name in ('single_training', 'prior_paired_training')}
    result = {}
    for row in replayed['teachers']:
        seed = str(row['seed']); parent_pin = config['parents'][seed]; cache_pin = cache_freeze['models'][seed]
        require(wire(row['parent']) == wire(parent_pin) and wire(row['cache']) == wire(cache_pin), 'teacher replay cache/parent differs')
        parent, cache = read(parent_pin), read(cache_pin)
        sources, counts = teacher_checker.verify_cache(cache, parent, projected['single_training'], projected['prior_paired_training'],
            seed=int(seed), parent_pin=parent_pin, expected_implementation=runner.runtime.producer_pins())
        expected = [{k: v[k] for k in ('id', 'source_sha256', 'proposed_time_span', 'logits')} for v in cache['rows']]
        require(row['cache_payload_sha256'] == digest(cache) and row['sources_sha256'] == digest(sources) and
                row['logits_and_sources_sha256'] == digest(expected) and
                wire(row['correct_training_rows_by_class']) == wire(counts) and
                row['model_state_before_sha256'] == row['model_state_after_sha256'] == digest(parent['model_state']),
                'teacher replay output/mask/state digest differs')
        require(type(row['exact_rows']) is int and row['exact_rows'] == 1632 and
                type(row['encoder_source_evaluations']) is int and row['encoder_source_evaluations'] == 1632 and
                type(row['encoder_batch_forwards']) is int and row['encoder_batch_forwards'] == 34,
                'individual teacher replay denominator differs')
        result[seed] = {'reference': cache_pin, 'payload_sha256': digest(cache)}
    return result


def inventory(freeze, data):
    require(freeze['schema'] == runner.SCHEMA and freeze['all_training_selection_and_generation_complete'] is True and
            freeze['fresh_references_opened'] is False and freeze['fresh_reference_guard']['premature_read_attempts'] == 0,
            'complete source-only experiment freeze required')
    require(wire(freeze['producer_pins']) == wire(runner.producer_pins()), 'fitting producer closure differs')
    config = read(freeze['config']); selection = read(freeze['selections']); initials = read(freeze['initialization_freeze'])
    parents = read(freeze['parent_evaluations'])
    teacher_binding = verify_teacher_replay(freeze, data, config, initials, selection)
    require(wire(selection['config']) == wire(initials['config']) == wire(freeze['config']) and
            wire(selection['initialization_freeze']) == wire(freeze['initialization_freeze']) and
            wire(selection['parent_evaluations']) == wire(freeze['parent_evaluations']), 'freeze lineage differs')
    require(selection['fresh_references_opened'] is False and selection['no_pipeline_promotion'] is True and
            parents['fresh_references_opened'] is False and parents['fresh_reference_guard']['premature_read_attempts'] == 0 and
            initials['fresh_references_opened'] is False and initials['fresh_reference_guard']['premature_read_attempts'] == 0,
            'parent/initial/selection seals differ')
    require(wire(parents['parents']) == wire(config['parents']) == wire(initials['parents']), 'parent references differ')
    require(wire(data['manifest_ref']) == wire(config['corpus_manifest']), 'admitted loader manifest differs')
    for seed in SEEDS:
        pin = config['parents'][str(seed)]; read_producer(pin)
        require(pin['sha256'] == runner.PARENT_SHAS[seed], 'fixed preceding parent differs')
    trials = {t['name']: t for t in selection['trials']}
    names = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    require(set(trials) == names and len(selection['trials']) == len(selection['trial_references']) == 6,
            'six unique matched trials required')
    actual = [read(pin) for pin in selection['trial_references']]
    require(len({t['name'] for t in actual}) == 6 and wire({t['name']: t for t in actual}) == wire(trials), 'trial file differs')
    for name, trial in trials.items():
        require(type(trial['seed']) is int and name == f"{trial['arm']}-{trial['seed']}" and
                trial['fresh_references_opened'] is False and trial['fresh_reference_guard']['premature_read_attempts'] == 0 and
                trial['selected_is_pipeline_promotion'] is False, 'trial identity/seals differ')
        seed = trial['seed']; parent_pin = config['parents'][str(seed)]
        require(wire(trial['parent_checkpoint']) == wire(parent_pin) and wire(trial['initial_checkpoint']) == wire(initials['models'][name]),
                'trial initial/parent checkpoint differs')
        cp = read(trial['initial_checkpoint']); parent_cp = read(parent_pin)
        require(cp['schema'] == CHECKPOINT_SCHEMA and type(cp['optimizer_steps']) is int and cp['optimizer_steps'] == 0 and
                cp['config']['arm'] == trial['arm'] and cp['config']['seed'] == seed and
                wire(cp['model_state']) == wire(parent_cp['model_state']) and
                wire(cp['parent']) == wire(parent_cp) and cp['parent_file_sha256'] == parent_pin['sha256'] and
                cp['optimizer_state']['parameters'] == {}, 'initial tensor/parent/fresh optimizer contract differs')
        require(wire(cp['teacher_cache']) == wire(teacher_binding[str(seed)]), 'initial teacher cache binding differs')
        require(wire(trial['initial_evaluation']) == wire(parents['evaluations'][str(seed)]), 'shared parent evaluation differs')
        parent_candidate = trial['parent_candidate']
        require(type(parent_candidate['steps']) is int and parent_candidate['steps'] == 0 and
                parent_candidate['decoder_kind'] == 'paired_owner_type' and wire(parent_candidate['checkpoint']) == wire(parent_pin),
                'candidate zero must be the exact parent')
        for panel in ADMITTED:
            e = parents['evaluations'][str(seed)][panel]
            require(wire(parent_candidate[panel+'_generation']) == wire(e['generation']) and
                    wire(parent_candidate[panel+'_metrics']) == wire(e['metrics']), 'parent candidate score binding differs')
            if panel in gates.PANELS:
                require(wire(parent_candidate[panel+'_gate_counts']) == wire(e['gate_counts']),
                        'parent candidate gate-count binding differs')
        require(wire([s['steps'] for s in trial['stages']]) == wire(list(STEPS[1:])), 'all prospective stages required')
        for stage in trial['stages']:
            read_producer(stage['checkpoint']); read_producer(stage['training_report'])
            require(stage['decoder_kind'] == 'stability_owner_type' and type(stage['eligible']) is bool, 'stage kind/eligibility differs')
            for panel in ADMITTED:
                require((panel+'_generation' in stage) is (panel in evaluated_panels(stage['steps'])) and
                        (panel+'_metrics' in stage) is (panel in evaluated_panels(stage['steps'])),
                        'stage training-diagnostic/source inventory differs')
        chosen = [s for s in [parent_candidate, *trial['stages']] if s['steps'] == trial['selected_steps']]
        require(len(chosen) == 1 and type(trial['selected_steps']) is int and
                wire(chosen[0]['checkpoint']) == wire(trial['selected_checkpoint']) and
                chosen[0]['decoder_kind'] == trial['selected_decoder_kind'] and
                trial['selected_parent_fallback'] is (trial['selected_steps'] == 0), 'selected checkpoint/parent alias differs')
    sources = {k: read(v) for k, v in freeze['sources'].items()}
    authoritative = {k: [corpus.source_row(r) for r in data[k]] for k in ADMITTED}
    authoritative.update({k: data[k+'_sources'] for k in PANELS[:2]})
    require(set(sources) == set(COUNTS), 'complete fourteen-panel source inventory required')
    for panel, values in sources.items():
        corpus.validate_query_inventory(values, expected=COUNTS[panel])
        require(wire(values) == wire(authoritative[panel]), 'saved sources differ from authoritative source pack')
    expected = {(f'parent-{seed}', panel) for seed in SEEDS for panel in PANELS}
    expected |= {(name+'__'+role, panel) for name in names for role in ('selected', 'final200') for panel in PANELS}
    seen = set(); unique = {}; physical = []
    for slot in freeze['logical_generations']:
        identity = (slot['slot'], slot['panel']); seed = slot['seed']
        require(identity in expected and identity not in seen and type(seed) is int and seed in SEEDS, 'duplicate/unknown logical slot')
        seen.add(identity)
        if slot['role'] == 'parent':
            require(slot['slot'] == f'parent-{seed}' and slot['arm'] == 'parent', 'parent slot differs')
            cp, kind, steps = config['parents'][str(seed)], 'paired_owner_type', 0
        else:
            name = f"{slot['arm']}-{seed}"; trial = trials[name]
            require(slot['slot'] == name+'__'+slot['role'], 'trial slot differs')
            if slot['role'] == 'selected': cp, kind, steps = trial['selected_checkpoint'], trial['selected_decoder_kind'], trial['selected_steps']
            else:
                require(slot['role'] == 'final200', 'unknown stage role')
                cp, kind, steps = trial['stages'][-1]['checkpoint'], 'stability_owner_type', 200
        require(wire(cp) == wire(slot['checkpoint']) and kind == slot['decoder_kind'] and type(slot['additional_steps']) is int and
                steps == slot['additional_steps'], 'logical slot checkpoint/kind/relative step differs')
        key = digest({'checkpoint': cp['sha256'], 'sources': freeze['sources'][slot['panel']]['sha256']})
        require(key == slot['generation_key'] and slot['executed_here'] is (key not in unique), 'alias identity or execution flag differs')
        if key in unique:
            require(wire(unique[key]['generation']) == wire(slot['generation']) and unique[key]['decoder_kind'] == kind, 'alias payload/kind differs')
        else:
            unique[key] = slot
            physical.append({'key': key, 'generation': slot['generation'], 'encoder_batch_forwards': math.ceil(COUNTS[slot['panel']]/48),
                             'encoder_source_evaluations': COUNTS[slot['panel']]})
    require(seen == expected and wire(physical) == wire(freeze['executed_generations']), 'full physical/logical generation inventory required')
    counts = {'logical_generation_slots': 28, 'logical_fresh_query_rows': 4032, 'physical_generation_files': len(physical),
              'physical_fresh_query_rows': sum(p['encoder_source_evaluations'] for p in physical),
              'physical_fresh_encoder_batch_forwards': sum(p['encoder_batch_forwards'] for p in physical),
              'total_optimizer_updates': 1200, 'training_encoder_batch_forwards': 1200, 'training_encoder_source_evaluations': 28800}
    for key, value in counts.items():require(type(freeze[key]) is int and freeze[key] == value, 'saved counter differs: '+key)
    require(wire(freeze['admitted_generation_counters']) == wire({'encoder_batch_forwards':1076,'encoder_source_evaluations':51648}),
            'parent/stage physical admitted counters differ')
    require(wire(freeze['teacher_preparation_counters']) == wire({'encoder_batch_forwards':68,'encoder_source_evaluations':3264}),
            'original teacher preparation counters differ')
    return config, trials, sources, unique, counts


def reference_candidate_audit(rows):
    """Reference-side coordinate validation only; never feeds model inference."""
    reports = []; ambiguous = multiple_same_type = 0; anchors_by_source = {}
    for row in rows:
        annotation = row['annotation']; source = corpus.source_row(row)
        require(annotation['gold_filtered_owner_candidates'] is True and
                annotation['candidate_inventory_usage'] == 'reference_only_not_inference_inputs' and
                annotation['independently_reviewed'] is False and annotation['source_semantics_verified'] is False and
                annotation['legal_gold'] is False, 'reference-side candidate authority differs')
        items = annotation['owner_candidates']; cues = annotation['attachment_cue_spans']
        cue_by_id = {x['owner_occurrence_id']: x['span'] for x in cues}
        require(len(cue_by_id) == len(cues) == len(items) and
                set(cue_by_id) == {x['owner_occurrence_id'] for x in items}, 'owner/cue occurrence join differs')
        supplied = []
        for item in items:
            anchor = item['anchor_span']
            expected = 'owner-'+candidates.digest([row['source_sha256'], item['owner_type'], anchor['char_start'], anchor['char_end']])
            require(item['owner_occurrence_id'] == expected, 'reference owner occurrence identity differs')
            anchors_by_source.setdefault(row['source_sha256'], {}).setdefault(item['owner_type'], set()).add(expected)
            supplied.append({'owner_type':item['owner_type'], 'anchor_span':anchor,
                             'scope_span':item['scope_span'], 'cue_span':cue_by_id[expected]})
        report = candidates.prepare_owner_candidates(source, supplied)
        require(not report['owner_occurrence_resolved'] and not report['candidate_inventory_complete'], 'candidate integrity acquired semantic authority')
        if row['label'] == 'ambiguous':
            ambiguous += 1
            require(len(items) >= 2 and annotation['unique_owner_type_asserted'] is False and
                    annotation['unique_owner_occurrence_asserted'] is False, 'ambiguity must retain alternatives')
        else:
            require(len(items) == 1 and items[0]['owner_type'] == row['label'], 'authored unique-type reference differs')
        multiple_same_type += len({x['owner_type'] for x in items}) < len(items)
        reports.append(report['report_sha256'])
    return {'queries':len(rows),'ambiguous_queries':ambiguous,'queries_with_multiple_same_type_candidates':multiple_same_type,
            'reference_sources_with_multiple_same_type_anchors':sum(any(len(ids)>1 for ids in owners.values()) for owners in anchors_by_source.values()),
            'coordinate_report_digest':digest(reports),'reference_only':True,'used_as_inference_inventory':False,
            'owner_occurrence_accuracy_measured':False,'semantic_ownership_certified':False}


def mask_layout(row):
    """Independent common body mask across explicitly annotated ancestors."""
    text=row['source_text'];a=row['annotation'];pieces=[];intervals=[]
    def bounds(v):
        require(type(v) is dict and set(v)=={'char_start','char_end','text'} and
                type(v['char_start']) is int and type(v['char_end']) is int and
                0<=v['char_start']<v['char_end']<=len(text) and text[v['char_start']:v['char_end']]==v['text'],
                'exact source-bound annotation span required')
        return v['char_start'],v['char_end']
    lo,cursor=bounds(a['heading_span']);require(lo==0,'heading must start at source origin')
    aliases={'action_object':'action','condition_anchor':'condition_predicate','exception_anchor':'exception_predicate'}
    for value in a.get('source_role_spans',a.get('lexical_spans',[])):
        require(set(value)=={'role','span'},'closed lexical role required')
        role=aliases.get(value['role'],value['role'])
        require(role in ('actor','action','condition_predicate','exception_predicate'),'known lexical role required')
        start,end=bounds(value['span']);intervals.append((start,end,'['+role+']'))
    for v in corpus.propose_time_spans(text):intervals.append((v['char_start'],v['char_end'],'[TIME]'))
    if 'modal_spans' in a:
        modals=[]
        for v in a['modal_spans']:
            start,end=bounds(v);require(v['text'] in ('shall','shall not','may'),'explicit modal required')
            modals.append((start,end))
    else:
        modals=[(m.start(),m.end()) for m in re.finditer(r'\b(?:shall not|shall|may)\b',text)
                if m.start()>=cursor and not any(lo<m.end() and m.start()<hi for lo,hi,_ in intervals)]
    require(bool(modals),'explicit source modal required')
    intervals.extend((lo,hi,'[MODAL]') for lo,hi in modals)
    for lo,hi,marker in sorted(intervals):
        require(cursor<=lo<hi<=len(text),'overlapping or heading-crossing source masks')
        pieces.extend((text[cursor:lo],marker));cursor=hi
    return ' '.join((''.join(pieces)+text[cursor:]).split())


def verify_stability_annotation(row):
    a=row['annotation'];text=row['source_text']
    require(a['schema']=='authored-temporal-stability-annotation/v1','current authored annotation schema required')
    def span(v):
        require(type(v) is dict and set(v)=={'char_start','char_end','text'} and
                type(v['char_start']) is int and type(v['char_end']) is int and
                0<=v['char_start']<v['char_end']<=len(text) and text[v['char_start']:v['char_end']]==v['text'],
                'exact source-bound annotation span required')
        return v['char_start'],v['char_end']
    def inside(v,outer):return outer['char_start']<=v['char_start']<v['char_end']<=outer['char_end']
    span(a['heading_span']);span(a['body_span']);span(a['time_span'])
    require(a['heading_span']['char_start']==0 and a['body_span']['char_start']==a['heading_span']['char_end']
            and a['body_span']['char_end']==len(text)-1 and text.endswith('.'),'complete heading/body/terminal coverage required')
    proposed=corpus.propose_time_spans(text)
    target={k:a['time_span'][k] for k in ('char_start','char_end')}
    require(wire(target)==wire(row['proposed_time_span']) and target in proposed,'queried temporal occurrence differs')
    require(type(a['source_occurrence_ordinal']) is int and a['source_occurrence_ordinal']==proposed.index(target)+1,
            'source temporal ordinal differs')
    roles={name:[] for name in ('actor','action','condition_predicate','exception_predicate')}
    for entry in a['source_role_spans']:
        require(set(entry)=={'role','span'} and entry['role'] in roles,'closed lexical role required')
        span(entry['span']);roles[entry['role']].append(entry['span'])
    require(len(roles['actor'])==len(roles['action'])>=1 and
            len(roles['condition_predicate'])==len(roles['exception_predicate'])==3,'complete actor/action/qualifier inventories required')
    norms=a['norm_occurrences'];require(type(norms) is list and len(norms)==len(roles['actor']),'all norm occurrences required')
    actors=[];actions=[];modals=[];normtimes=[];previous_end=-1
    for norm in norms:
        require(set(norm)=={'actor_span','modal_span','action_span','time_span','clause_span'},'closed norm occurrence required')
        for key in ('actor_span','modal_span','action_span','clause_span'):span(norm[key])
        actor,modal,action,extent=(norm[k] for k in ('actor_span','modal_span','action_span','clause_span'))
        require(previous_end<=extent['char_start'] and inside(extent,a['body_span']) and
                all(inside(v,extent) for v in (actor,modal,action)) and
                actor['char_end']<=modal['char_start']<modal['char_end']<=action['char_start'],
                'ordered nonoverlapping norm occurrence anchors required')
        previous_end=extent['char_end']
        require(modal['text']=={'O':'shall','P':'may','F':'shall not'}[a['modality']],'norm modal source cue differs')
        actors.append(actor);modals.append(modal);actions.append(action)
        time=norm['time_span']
        if time is not None:
            span(time);require(inside(time,extent),'norm time outside its occurrence extent')
            require({k:time[k] for k in ('char_start','char_end')} in proposed,'norm time is not a proposed occurrence')
            realized='before_actor' if time['char_end']<=actor['char_start'] else 'after_modal' if modal['char_end']<=time['char_start'] and time['char_end']<=action['char_start'] else 'after_action' if time['char_start']>=action['char_end'] else None
            require(realized is not None and realized==a['norm_time_placement'],'realized norm deadline placement differs')
            normtimes.append(time)
    for actual,expected in ((actors,roles['actor']),(actions,roles['action']),(modals,a['modal_spans'])):
        require(wire(actual)==wire(expected),'norm occurrences do not exactly cover all source anchors/modals')
    require(len({(v['char_start'],v['char_end']) for v in normtimes})==len(normtimes),'duplicate norm time occurrence')
    blocks=a['block_spans'];require(set(blocks)=={'norm','condition','exception'},'complete block inventory required')
    for block in blocks.values():span(block)
    require(blocks['norm']['char_start']==norms[0]['clause_span']['char_start'] and
            blocks['norm']['char_end']==norms[-1]['clause_span']['char_end'],'norm block extent differs')
    order=a['qualifier_order'];require(order in (['condition','exception'],['exception','condition']),'explicit qualifier order required')
    first,last=(blocks[k] for k in order)
    require(first['char_end']<=last['char_start'],'qualifier blocks overlap/order differs')
    for owner in ('condition','exception'):
        require(all(inside(v,blocks[owner]) for v in roles[owner+'_predicate']),'qualifier atom outside its block')
        require(blocks[owner]['text'].lstrip('(').startswith('if ' if owner=='condition' else 'unless '),'qualifier cue differs')
    family=a['structural_family'];joint=a['interposition_span']
    if family=='matched_placement_layout':
        require(joint is None,'lexical control cannot claim interposition')
        placement_prior.body_layout(row)
    else:
        require(family in ('actor_joint_modal_action','actor_modal_joint_action') and
                a['enclosure_family']=='interposed_joint_qualifiers' and a['layout_family']==family,'declared interposition family required')
        span(joint)
        require(joint['text'].startswith('(') and joint['text'].endswith(')') and
                first['char_start']==joint['char_start']+1 and last['char_end']==joint['char_end']-1 and
                text[first['char_end']:last['char_start']]==', ' and inside(joint,norms[0]['clause_span']),
                'complete joint qualifier enclosure required')
        firstnorm=norms[0]
        left=firstnorm['actor_span'] if family=='actor_joint_modal_action' else firstnorm['modal_span']
        right=firstnorm['modal_span'] if family=='actor_joint_modal_action' else firstnorm['action_span']
        require(left['char_end']<=joint['char_start']<joint['char_end']<=right['char_start'],
                'actual interposition anchor order differs')
        require(all(not (joint['char_start']<t['char_end'] and t['char_start']<joint['char_end']) for t in normtimes),
                'norm deadline silently lies inside qualifier enclosure')
    owner=a['authored_local_owner_type'];require(owner in ('norm','condition','exception'),'known local owner type required')
    local=[v for v in a['owner_candidates'] if v['owner_type']==owner]
    require(len(local)==1,'unique declared local reference candidate required')
    role='action' if owner=='norm' else owner+'_predicate';anchors=roles[role]
    require(local[0]['anchor_span'] in anchors and type(a['local_atom_ordinal']) is int and
            a['local_atom_ordinal']==anchors.index(local[0]['anchor_span'])+1,'local atom ordinal differs')
    if row['label']=='norm':require(a['time_span'] in normtimes,'norm query lacks exact norm time occurrence')
    return {'norm_occurrences':len(norms),'realized_norm_deadlines':len(normtimes),'structural_family':family}


def body_layout(row):
    if 'norm_occurrences' in row['annotation']:verify_stability_annotation(row)
    else:placement_prior.body_layout(row)
    return mask_layout(row)


def exposure_audit(data,fresh_targets,ledger,exposure):
    manifest=data['manifest'];prior_data=data['prior_inputs']
    require(wire(manifest['prior_corpus'])==wire(prior_data['manifest_ref']),'prior placement corpus binding differs')
    pools={p:data[p] for p in TRAIN}
    pools['placement_tuning']=data['placement_tuning'];pools.update(data['retention_targets'])
    old_manifest=read(prior_data['legacy']['manifest']['prior_corpus']);source_pins=old_manifest['historical_source_packs']
    require(exposure['schema']=='temporal-stability-exposure/v1' and wire(exposure['prior_corpus'])==wire(manifest['prior_corpus']) and
            wire(exposure['historical_source_packs'])==wire(source_pins) and exposure['shared_attachment_grammar'] is True and
            exposure['independent_legal_gold'] is False,'exposure source provenance differs')
    normalize=lambda text:' '.join(text.casefold().split())
    history=set();history_groups=set();history_literals=set();prior_layouts=set();pool_summary={}
    for name,rows in pools.items():
        layouts={mask_layout(r) for r in rows};prior_layouts.update(layouts)
        history.update(normalize(r['source_text']) for r in rows);history_groups.update(r['group_id'] for r in rows)
        history_literals.update(r['annotation']['time_span']['text'] for r in rows)
        pool_summary[name]={'queries':len(rows),'sources':len({r['source_sha256'] for r in rows}),
                            'body_layouts':sorted(layouts),'rows_sha256':digest(rows)}
    for pin in source_pins:
        for r in read(pin):
            require(set(r)=={'candidate_id','source_text','source_sha256'} and r['source_sha256']==hashlib.sha256(r['source_text'].encode()).hexdigest(),
                    'historical source digest differs')
            history.add(normalize(r['source_text']))
            history_literals.update(r['source_text'][v['char_start']:v['char_end']] for v in corpus.propose_time_spans(r['source_text']))
    require(wire(pool_summary)==wire(exposure['prior_annotated_pools']) and len(pool_summary)==12 and
            len(history)==exposure['historical_unique_sources_checked'] and len(prior_layouts)==exposure['prior_normalized_body_layout_count'],
            'historical annotated/layout/source inventory differs')
    train_layouts={mask_layout(r) for r in data['placement_training']};seen=set();groups_seen=set();literals_seen=set();new_layouts={};results={}
    require(set(exposure['panels'])==set(fresh_targets)==set(PANELS),'complete two-panel current holdout required')
    for split,rows in fresh_targets.items():
        texts={normalize(r['source_text']) for r in rows};groups={r['group_id'] for r in rows}
        literals={r['annotation']['time_span']['text'] for r in rows}
        require(not texts&(history|seen) and not groups&(history_groups|groups_seen) and not literals&(history_literals|literals_seen),
                'historical or cross-panel source/group/literal overlap')
        seen.update(texts);groups_seen.update(groups);literals_seen.update(literals)
        masked=[body_layout(row) for row in rows];new_layouts[split]=set(masked)
        by_source={}
        for row in rows:by_source.setdefault(row['source_sha256'],[]).append(row)
        for source_rows in by_source.values():
            intervals=[r['proposed_time_span'] for r in source_rows]
            require(wire(sorted(intervals,key=lambda x:x['char_start']))==wire(corpus.propose_time_spans(source_rows[0]['source_text'])),
                    'source-complete time query inventory differs')
            require(len({wire(r['annotation']['norm_occurrences']) for r in source_rows})==1,
                    'same source received inconsistent norm occurrence inventory')
        expected={'queries':len(rows),'sources':len(texts),'units':len({r['annotation']['unit_id'] for r in rows}),
            'class_counts':dict(Counter(r['label'] for r in rows)),
            'modality_by_class':{c:dict(Counter(r['annotation']['modality'] for r in rows if r['label']==c)) for c in metric.CLASSES},
            'time_form_by_class':{c:dict(Counter(r['annotation']['time_form'] for r in rows if r['label']==c)) for c in metric.CLASSES},
            'placement_by_class':{c:dict(Counter(r['annotation']['norm_time_placement'] for r in rows if r['label']==c)) for c in metric.CLASSES},
            'structural_family_counts':dict(Counter(r['annotation']['structural_family'] for r in rows)),
            'qualifier_order_counts':dict(Counter('_'.join(r['annotation']['qualifier_order']) for r in rows)),
            'normalized_body_layouts':sorted(set(masked)),'matches_prior_body_layout_queries':sum(v in prior_layouts for v in masked),
            'matches_placement_train_body_layout_queries':sum(v in train_layouts for v in masked),
            'source_hashes':sorted(by_source),'time_literals':sorted(literals)}
        require(wire(expected)==wire(exposure['panels'][split]),'independent exposure reconstruction differs: '+split)
        expected_families={'matched_placement_layout':144} if split=='fresh_lexical' else {'actor_joint_modal_action':72,'actor_modal_joint_action':72}
        require(expected['structural_family_counts']==expected_families,'prospective structural family counts differ')
        results[split]={k:v for k,v in expected.items() if k not in ('normalized_body_layouts','source_hashes','time_literals')}
    require(not new_layouts['fresh_structural']&(prior_layouts|new_layouts['fresh_lexical']) and
            results['fresh_lexical']['matches_placement_train_body_layout_queries']==144,'heldout structure/matched lexical profile differs')
    require(wire(exposure['prospective_structural_families'])==wire(['actor_joint_modal_action','actor_modal_joint_action']) and
            exposure['norm_placement_metadata_only_realized_on_norm_queries'] is True and
            all(type(exposure[k]) is int and exposure[k]==0 for k in ('historical_source_overlap','cross_panel_source_overlap','cross_panel_group_overlap','cross_panel_literal_overlap')),
            'exposure disclosure differs')
    require(ledger['schema']=='temporal-stability-reference-ledger/v1' and
            ledger['candidate_inventory_usage']=='reference_only_not_inference_inputs','reference ledger authority differs')
    for split,rows in fresh_targets.items():
        require(wire(ledger['annotations'][split])==wire([{k:r[k] for k in ('id','source_sha256','group_id','label','annotation')} for r in rows]),
                'fresh ledger/source/label join differs')
    return {'panels':results,'historical_unique_sources_checked':len(history),'historical_annotated_pools':len(pools),
            'structural_holdout_matches_admitted_body_layouts':0,'shared_attachment_grammar':True,'independent_legal_gold':False,
            'norm_time_placement_is_realized_only_on_norm_queries':True,
            'all_declared_norm_deadline_positions_source_verified':True,
            'reference_side_candidate_audits':{split:reference_candidate_audit(rows) for split,rows in fresh_targets.items()}}


def replay(freeze_path, output):
    freeze_pin = reference(freeze_path); freeze = read(freeze_pin)
    data, guard = load_inputs(freeze)
    _, trials, sources, unique, counts = inventory(freeze, data)
    rows = []; batches = queries = 0; model = None; current_checkpoint = None
    for key, slot in sorted(unique.items(), key=lambda pair:(pair[1]['checkpoint']['sha256'],pair[0])):
        source = sources[slot['panel']]; saved = read(slot['generation'])
        expected = generation(saved, slot['checkpoint'], freeze['sources'][slot['panel']], source, **physical_metadata(slot))
        model_key = (slot['checkpoint']['sha256'],slot['decoder_kind'])
        if current_checkpoint != model_key:
            # Construction/restoration performs no encoder forward. Each exact
            # checkpoint is loaded once for all of its evaluation panels.
            _, model = runner.load_decoder(slot['checkpoint'],slot['decoder_kind'])
            current_checkpoint = model_key
        before_batches, before_queries = model.encoder_batch_forwards, model.encoder_source_evaluations
        actual = []
        for begin in range(0,len(source),48):actual.extend(model.predict_many(source[begin:begin+48]))
        require(wire(actual) == wire(expected), 'independent source-only checkpoint replay differs')
        nb, nq = model.encoder_batch_forwards-before_batches, model.encoder_source_evaluations-before_queries
        require(nb == math.ceil(len(source)/48) and nq == len(source), 'independent replay counters differ')
        batches += nb; queries += nq
        rows.append({'key':key,'checkpoint':slot['checkpoint'],'decoder_kind':slot['decoder_kind'],
                     'sources':freeze['sources'][slot['panel']],'generation':slot['generation'],
                     'rows_sha256':digest(actual),'exact_rows':len(actual),'encoder_batch_forwards':nb,'encoder_source_evaluations':nq})
        print(json.dumps({'phase':'independent_replay','complete':len(rows),'unique_jobs':len(unique),'queries':queries}),flush=True)
    require(queries == counts['physical_fresh_query_rows'] and batches == counts['physical_fresh_encoder_batch_forwards'],
            'complete unique evaluation replay required')
    require(not guard['premature_read_attempts'] and guard['released'] is False, 'replay cannot release fresh references')
    return write(output,{'schema':'legal-stability-owner-type-independent-replay/v1','generation_freeze':freeze_pin,
                        'independent_teacher_replay':freeze['independent_teacher_replay'],
                        'teacher_cache_freeze':freeze['teacher_cache_freeze'],
                        'producer_files':producer_pins(),'replays':rows,'exact_replay':True,
                        'encoder_batch_forwards':batches,'encoder_source_evaluations':queries,
                        'fresh_references_opened':False,'fresh_reference_guard':guard,
                        'logical_aliases_are_not_reexecutions':True,'pipeline_promotion':False})


def check_replay(freeze, freeze_pin, replayed, sources, unique, counts):
    require(replayed['schema'] == 'legal-stability-owner-type-independent-replay/v1' and replayed['exact_replay'] is True and
            wire(replayed['generation_freeze']) == wire(freeze_pin) and replayed['fresh_references_opened'] is False and
            replayed['fresh_reference_guard']['released'] is False and not replayed['fresh_reference_guard']['premature_read_attempts'],
            'complete sealed independent replay must precede reference release')
    require(wire(replayed['independent_teacher_replay']) == wire(freeze['independent_teacher_replay']) and
            wire(replayed['teacher_cache_freeze']) == wire(freeze['teacher_cache_freeze']),
            'prefit teacher evidence changed between final replay and scoring')
    require(wire(replayed['producer_files']) == wire(producer_pins()), 'qualifier producer closure changed after replay')
    for pin in replayed['producer_files']:read_producer(pin)
    receipts = replayed['replays']
    require(len(receipts) == len(unique) and {r['key'] for r in receipts} == set(unique), 'complete unique replay receipt inventory required')
    batches = queries = 0
    for receipt in receipts:
        slot = unique[receipt['key']]; source = sources[slot['panel']]; saved = read(slot['generation'])
        expected = generation(saved,slot['checkpoint'],freeze['sources'][slot['panel']],source,**physical_metadata(slot))
        require(wire(receipt['generation']) == wire(slot['generation']) and wire(receipt['checkpoint']) == wire(slot['checkpoint']) and
                receipt['decoder_kind'] == slot['decoder_kind'] and wire(receipt['sources']) == wire(saved['sources']) and
                receipt['rows_sha256'] == digest(expected) and type(receipt['exact_rows']) is int and receipt['exact_rows'] == len(source) and
                type(receipt['encoder_batch_forwards']) is int and receipt['encoder_batch_forwards'] == math.ceil(len(source)/48) and
                type(receipt['encoder_source_evaluations']) is int and receipt['encoder_source_evaluations'] == len(source), 'replay payload/source/checkpoint binding differs')
        batches += receipt['encoder_batch_forwards']; queries += receipt['encoder_source_evaluations']
    require(type(replayed['encoder_batch_forwards']) is int and batches == replayed['encoder_batch_forwards'] == counts['physical_fresh_encoder_batch_forwards'] and
            type(replayed['encoder_source_evaluations']) is int and queries == replayed['encoder_source_evaluations'] == counts['physical_fresh_query_rows'],
            'replay aggregate counters differ')


def score_admitted(freeze, trials, sources, data):
    labels = {p:{r['id']:r['label'] for r in data[p]} for p in ADMITTED}
    admitted=[];choices={};cache={};physical_rows=physical_batches=0
    for name,trial in sorted(trials.items()):
        values={}
        for step in STEPS:
            stage=trial['parent_candidate'] if step==0 else next(s for s in trial['stages'] if s['steps']==step)
            kind=stage['decoder_kind'];panel_scores={};selection_scores={}
            for panel in evaluated_panels(step):
                pin=stage[panel+'_generation'];saved=read(pin)
                predictions=generation(saved,stage['checkpoint'],freeze['sources'][panel],sources[panel],
                    arm='mixed_occurrences' if kind=='paired_owner_type' else trial['arm'],seed=trial['seed'],
                    step=200 if kind=='paired_owner_type' else step,decoder_kind=kind)
                key=digest({'generation':pin['sha256'],'sources':freeze['sources'][panel]['sha256'],'labels':labels[panel]})
                if key not in cache:
                    cache[key]=metric.score(sources[panel],predictions,labels[panel])
                    physical_rows+=len(predictions);physical_batches+=saved['encoder_batch_forwards']
                result=cache[key];reconcile_metrics(result,stage[panel+'_metrics'])
                panel_scores[panel]={k:v for k,v in result.items() if k!='rows'}
                if panel in gates.PANELS:
                    expected=gates.gate_counts(result)
                    require(wire(expected)==wire(stage[panel+'_gate_counts']),'saved row-bound gate counts differ')
                    selection_scores[panel]=result
            values[step]=selection_scores
            admitted.append({'trial':name,'steps':step,'checkpoint':stage['checkpoint'],'decoder_kind':kind,'scores':panel_scores})
        choice=independent_selection(values)
        require(choice['selected_steps']==trial['selected_steps'],'independent admitted selection differs')
        require(wire(choice)==wire(trial['selection_receipt']),'complete source-bound selection receipt differs')
        for stage in trial['stages']:
            require(stage['eligible'] is (stage['steps'] in choice['eligible_steps']),'saved stage eligibility differs')
        choices[name]=choice
    require(len(cache)==204 and physical_rows==51648 and physical_batches==1076,
            'complete parent/stage admitted score denominator differs')
    return admitted,choices,{'physical_saved_files_scored':len(cache),'physical_saved_query_rows_scored':physical_rows,
        'logical_stage_scores':len(admitted),
        'logical_saved_query_rows_scored':sum(sum(value['count'] for value in row['scores'].values()) for row in admitted),
        'admitted_outputs_numerically_replayed':False}


def score(freeze_path, replay_path, output):
    freeze_pin = reference(freeze_path); freeze = read(freeze_pin); replay_pin = reference(replay_path); replayed = read(replay_pin)
    data, guard = load_inputs(freeze)
    config,trials,sources,unique,counts = inventory(freeze,data)
    check_replay(freeze,freeze_pin,replayed,sources,unique,counts)
    admitted,choices,admitted_counts = score_admitted(freeze,trials,sources,data)
    require(not guard['premature_read_attempts'], 'premature fresh access attempted before admitted selection verification')
    # The only fresh release transition follows byte checks, exact numerical
    # replay and independent admitted scoring/selection. No gate can change here.
    guard['released'] = True
    manifest = data['manifest']; artifacts = manifest['artifacts']
    ledger = read(artifacts['fresh_annotation_ledger']); exposure = read(artifacts['exposure_audit'])
    targets = {panel:read(artifacts[panel+'_targets']) for panel in PANELS[:2]}
    for panel,rows in targets.items():
        # This runs only after release: exact frozen authored-record replay
        # validates closed annotations/countermodels in addition to the
        # independent source-coordinate and exposure reconstruction below.
        corpus.validate_units(rows,ledger['units'][panel],panel,reconstruct=True)
        require(wire([corpus.source_row(r) for r in rows]) == wire(sources[panel]), 'fresh target/query order differs')
    annotation_audit = exposure_audit(data,targets,ledger,exposure)
    labels = {panel:{r['id']:r['label'] for r in rows} for panel,rows in targets.items()}
    physical = {}
    for key,slot in unique.items():
        source = sources[slot['panel']]; value = read(slot['generation'])
        predictions = generation(value,slot['checkpoint'],freeze['sources'][slot['panel']],source,**physical_metadata(slot))
        result = metric.score(source,predictions,labels[slot['panel']])
        physical[key] = {'generation':slot['generation'],'metrics':result,
                         'occurrence_diagnostics':metric.occurrence_diagnostics(source,predictions,labels[slot['panel']])}
    logical = [{**slot,'metrics':{k:v for k,v in physical[slot['generation_key']]['metrics'].items() if k!='rows'},
                'occurrence_summary':{k:v for k,v in physical[slot['generation_key']]['occurrence_diagnostics'].items() if k!='groups'}}
               for slot in freeze['logical_generations']]
    comparisons = []
    for seed in SEEDS:
        for panel in PANELS:
            parent = next(r for r in logical if r['seed']==seed and r['panel']==panel and r['role']=='parent')
            selected = {r['arm']:r for r in logical if r['seed']==seed and r['panel']==panel and r['role']=='selected'}
            for base,other in [('parent',arm) for arm in ARMS]+[('placement_ce',arm) for arm in ARMS if arm != 'placement_ce']:
                left = parent if base=='parent' else selected[base]; right = selected[other]
                comparisons.append({'seed':seed,'panel':panel,'baseline':base,'arm':other,
                    **paired_comparison(physical[left['generation_key']]['metrics'],physical[right['generation_key']]['metrics'])})
    return write(output,{'schema':SCHEMA,'generation_freeze':freeze_pin,'replay_freeze':replay_pin,
        'independent_teacher_replay':freeze['independent_teacher_replay'],'teacher_cache_freeze':freeze['teacher_cache_freeze'],
        'prefit_teacher_replay_counters':{'encoder_batch_forwards':68,'encoder_source_evaluations':3264,
                                         'reexecuted_during_final_qualification':False},
        'original_teacher_preparation_counters':freeze['teacher_preparation_counters'],
        'producer_files':producer_pins(),'reference_release_after_replay_and_admitted_selection':True,'fresh_reference_guard':guard,
        'released_references':[artifacts[k] for k in runner.SEALED_KEYS],'admitted_scores':admitted,'admitted_scoring':admitted_counts,
        'independent_selection':choices,'independently_selected_steps':{k:v['selected_steps'] for k,v in choices.items()},
        'physical_evaluation_scores':physical,'logical_evaluation_scores':logical,'paired_selected_comparisons':comparisons,
        'counters':counts,'legacy_counter_names_fresh_include_exposed_regression_panels':False,
        'current_fresh_logical_query_rows':4032,'exposed_regression_logical_query_rows':0,
        'annotation_and_exposure_audit':annotation_audit,'extra_replay_encoder_batch_forwards':replayed['encoder_batch_forwards'],
        'authored_references_checked_against_frozen_producer_after_release':True,
        'extra_replay_query_evaluations':replayed['encoder_source_evaluations'],'current_reference_results_used_for_selection':False,
        'owner_occurrence_resolved':False,'independent_legal_gold':False,'pipeline_promotion':False,
        'admitted_outputs_numerically_replayed':False,'optimizer_trajectory_numerically_replayed':False,
        'latent_conditioning_improvement_tested':False,'attachment_or_formula_acceptance_measured':False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['replay','score']);parser.add_argument('--generation-freeze',required=True)
    parser.add_argument('--replay-freeze');parser.add_argument('--output',required=True);args=parser.parse_args()
    if args.phase=='replay':result=replay(args.generation_freeze,args.output)
    else:
        if not args.replay_freeze:parser.error('--replay-freeze is required for score')
        result=score(args.generation_freeze,args.replay_freeze,args.output)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()

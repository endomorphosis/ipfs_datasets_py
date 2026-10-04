#!/usr/bin/env python3
"""Independent saved-input, replay and scoring checks for paired owner types.

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
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metric
from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as candidates
from scripts.ops.legal_ir import qualify_legal_temporal_ownership_head_v2 as old
from scripts.ops.legal_ir import run_legal_paired_temporal_ownership as runner

SCHEMA = 'legal-paired-owner-type-independent-qualification/v1'
ARMS = ('single_replay', 'mixed_occurrences', 'ambiguity_weighted')
SEEDS = (1730, 1731)
STEPS = (0, 50, 100, 200)
CHECKPOINT_SCHEMA = 'legal-paired-temporal-owner-type-checkpoint/v1'
ADMITTED = ('single_training', 'paired_training', 'single_tuning', 'paired_tuning')
PANELS = ('fresh_lexical', 'fresh_structural', 'old_single_fresh', 'old_multi_fresh')
COUNTS = dict(zip((*ADMITTED, *PANELS), (768, 864, 144, 288, 144, 144, 192, 96)))
require = metric.require


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


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
        require(pin['schema'] in (CHECKPOINT_SCHEMA, 'legal-temporal-owner-type-checkpoint/v1') and
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
    """Unchanged parent retention on old tuning; rank only new tuning."""
    require(type(scores) is dict and set(scores) == set(STEPS) and
            all(type(k) is int for k in scores), 'parent and all prospective stages required')
    parent = scores[0]['single_tuning']; eligible = {}; ranks = {}
    for step in STEPS:
        single, paired = scores[step]['single_tuning'], scores[step]['paired_tuning']
        for value, count in ((single, 144), (paired, 288)):
            require(type(value['count']) is int and value['count'] == count and
                    type(value['correct']) is int and 0 <= value['correct'] <= count and
                    type(value['accepted_type_errors']) is int and 0 <= value['accepted_type_errors'] <= count-value['correct'] and
                    type(value['macro_f1']) in (int, float) and math.isfinite(value['macro_f1']) and 0 <= value['macro_f1'] <= 1 and
                    type(value['mean_nll']) in (int, float) and math.isfinite(value['mean_nll']) and value['mean_nll'] >= 0,
                    'closed finite selection count/range contract required')
        eligible[step] = single['correct'] >= parent['correct'] and single['accepted_type_errors'] <= parent['accepted_type_errors']
        ranks[step] = (-paired['macro_f1'], paired['mean_nll'], step)
    chosen = min((s for s in STEPS if eligible[s]), key=ranks.__getitem__)
    return {'selected_steps': chosen, 'eligible_steps': [s for s in STEPS if eligible[s]],
            'ranking': {str(s): list(ranks[s]) for s in STEPS},
            'old_single_correct_floor': parent['correct'], 'old_single_accepted_error_ceiling': parent['accepted_type_errors'],
            'fresh_results_used': False, 'coverage_gate_applied': False, 'pipeline_promotion': False}


def generation(value, checkpoint, sources_pin, sources, *, arm, seed, step, decoder_kind='paired_owner_type'):
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
    paths.update(str(Path(m.__file__).resolve()) for m in (sys.modules[__name__], metric, corpus, old))
    return [reference(path) for path in sorted(paths)]


def physical_metadata(slot):
    return {'arm': 'finetune_occurrence' if slot['decoder_kind'] == 'old_owner_type' else slot['arm'],
            'seed': slot['seed'], 'step': 200 if slot['decoder_kind'] == 'old_owner_type' else slot['additional_steps'],
            'decoder_kind': slot['decoder_kind']}


def load_inputs(freeze):
    config = read(freeze['config']); manifest = read(config['corpus_manifest'])
    guard = phase_guard(manifest, runner.SEALED_KEYS)
    runner.load_config(freeze['config']['path'])
    data = corpus.load_training_inputs(config['corpus_manifest']['path'])
    return data, guard


def inventory(freeze, data):
    require(freeze['schema'] == runner.SCHEMA and freeze['all_training_selection_and_generation_complete'] is True and
            freeze['fresh_references_opened'] is False and freeze['fresh_reference_guard']['premature_read_attempts'] == 0,
            'complete source-only experiment freeze required')
    require(wire(freeze['producer_pins']) == wire(runner.producer_pins()), 'fitting producer closure differs')
    config = read(freeze['config']); selection = read(freeze['selections']); initials = read(freeze['initialization_freeze'])
    parents = read(freeze['parent_evaluations'])
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
        require(wire(trial['initial_evaluation']) == wire(parents['evaluations'][str(seed)]), 'shared parent evaluation differs')
        parent_candidate = trial['parent_candidate']
        require(type(parent_candidate['steps']) is int and parent_candidate['steps'] == 0 and
                parent_candidate['decoder_kind'] == 'old_owner_type' and wire(parent_candidate['checkpoint']) == wire(parent_pin),
                'candidate zero must be the exact parent')
        for panel in ADMITTED:
            e = parents['evaluations'][str(seed)][panel]
            require(wire(parent_candidate[panel+'_generation']) == wire(e['generation']) and
                    wire(parent_candidate[panel+'_metrics']) == wire(e['metrics']), 'parent candidate score binding differs')
        require(wire([s['steps'] for s in trial['stages']]) == wire(list(STEPS[1:])), 'all prospective stages required')
        for stage in trial['stages']:
            read_producer(stage['checkpoint']); read_producer(stage['training_report'])
            require(stage['decoder_kind'] == 'paired_owner_type' and type(stage['eligible']) is bool, 'stage kind/eligibility differs')
        chosen = [s for s in [parent_candidate, *trial['stages']] if s['steps'] == trial['selected_steps']]
        require(len(chosen) == 1 and type(trial['selected_steps']) is int and
                wire(chosen[0]['checkpoint']) == wire(trial['selected_checkpoint']) and
                chosen[0]['decoder_kind'] == trial['selected_decoder_kind'] and
                trial['selected_parent_fallback'] is (trial['selected_steps'] == 0), 'selected checkpoint/parent alias differs')
    sources = {k: read(v) for k, v in freeze['sources'].items()}
    authoritative = {k: [corpus.source_row(r) for r in data[k]] for k in ADMITTED}
    authoritative.update({k: data[k+'_sources'] for k in PANELS[:2]})
    authoritative.update({'old_single_fresh': data['regression_sources']['single'], 'old_multi_fresh': data['regression_sources']['multi']})
    require(set(sources) == set(COUNTS), 'complete eight-panel source inventory required')
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
            cp, kind, steps = config['parents'][str(seed)], 'old_owner_type', 0
        else:
            name = f"{slot['arm']}-{seed}"; trial = trials[name]
            require(slot['slot'] == name+'__'+slot['role'], 'trial slot differs')
            if slot['role'] == 'selected': cp, kind, steps = trial['selected_checkpoint'], trial['selected_decoder_kind'], trial['selected_steps']
            else:
                require(slot['role'] == 'final200', 'unknown stage role')
                cp, kind, steps = trial['stages'][-1]['checkpoint'], 'paired_owner_type', 200
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
    counts = {'logical_generation_slots': 56, 'logical_fresh_query_rows': 8064, 'physical_generation_files': len(physical),
              'physical_fresh_query_rows': sum(p['encoder_source_evaluations'] for p in physical),
              'physical_fresh_encoder_batch_forwards': sum(p['encoder_batch_forwards'] for p in physical),
              'total_optimizer_updates': 1200, 'training_encoder_batch_forwards': 1200, 'training_encoder_source_evaluations': 28800}
    for key, value in counts.items():require(type(freeze[key]) is int and freeze[key] == value, 'saved counter differs: '+key)
    require(wire(freeze['admitted_generation_counters']) == wire({'encoder_batch_forwards':860,'encoder_source_evaluations':41280}),
            'parent/stage physical admitted counters differ')
    return config, trials, sources, unique, counts


def reference_candidate_audit(rows):
    """Reference-side coordinate validation only; never feeds model inference."""
    reports = []; ambiguous = multiple_same_type = 0
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
            'coordinate_report_digest':digest(reports),'reference_only':True,'used_as_inference_inventory':False,
            'owner_occurrence_accuracy_measured':False,'semantic_ownership_certified':False}


def body_layout(row):
    """Independent offset-preserving masking of exact declared lexical roles."""
    text = row['source_text']; annotation = row['annotation']; intervals = []
    def span(value):
        require(type(value) is dict and set(value) == {'char_start','char_end','text'} and
                type(value['char_start']) is int and type(value['char_end']) is int and
                0 <= value['char_start'] < value['char_end'] <= len(text) and
                text[value['char_start']:value['char_end']] == value['text'], 'annotation span differs from source')
        return value['char_start'], value['char_end']
    heading = annotation['heading_span']; lo, start = span(heading)
    require(lo == 0, 'heading must be the exact prefix')
    actor = None
    for item in annotation['source_role_spans']:
        require(set(item) == {'role','span'} and item['role'] in ('actor','action','condition_predicate','exception_predicate'),
                'declared lexical role inventory differs')
        lo, hi = span(item['span']); intervals.append((lo,hi,'['+item['role']+']'))
        if item['role'] == 'actor':
            require(actor is None, 'one actor anchor required'); actor = item['span']
    require(actor is not None, 'actor required')
    for value in corpus.propose_time_spans(text):intervals.append((value['char_start'],value['char_end'],'[TIME]'))
    modal = re.match(r' (shall not|shall|may)(?=[, ])', text[actor['char_end']:])
    require(modal is not None, 'explicit declared modal required')
    lo = actor['char_end']+1; intervals.append((lo,lo+len(modal.group(1)),'[MODAL]'))
    cursor = start; pieces = []
    for lo, hi, marker in sorted(intervals):
        require(cursor <= lo < hi <= len(text), 'overlapping or heading-crossing lexical masks')
        pieces.extend((text[cursor:lo],marker)); cursor = hi
    pieces.append(text[cursor:]); return ''.join(pieces)


def exposure_audit(data, fresh_targets, ledger, exposure):
    manifest = data['manifest']; prior = read(manifest['prior_corpus'])
    require(exposure['schema'] == 'paired-temporal-ownership-exposure/v1' and
            exposure['shared_local_attachment_grammar'] is True and exposure['independent_legal_gold'] is False and
            wire(exposure['prior_corpus_manifest']) == wire(manifest['prior_corpus']) and
            wire(exposure['historical_source_packs']) == wire(prior['historical_source_packs']), 'exposure provenance differs')
    normalized = lambda text: ' '.join(text.casefold().split())
    historical = set()
    for pin in prior['historical_source_packs']:
        for r in read(pin):
            require(set(r) == {'candidate_id','source_text','source_sha256'} and
                    hashlib.sha256(r['source_text'].encode()).hexdigest() == r['source_sha256'], 'historical source binding differs')
            historical.add(normalized(r['source_text']))
    for key in ('train_targets','tuning_targets','fresh_sources','multi_fresh_sources'):
        historical.update(normalized(r['source_text']) for r in read(prior['artifacts'][key]))
    require(exposure['historical_unique_sources_checked'] == len(historical), 'historical source denominator differs')
    panels = {'train':data['paired_training'],'tuning':data['paired_tuning'],**fresh_targets}
    require(set(exposure['panels']) == set(panels), 'exposure panel inventory differs')
    layouts = {}; results = {}; seen = set(); groups_seen = set(); literal_seen = set()
    for split, rows in panels.items():
        sources = {normalized(r['source_text']) for r in rows}; groups = {r['group_id'] for r in rows}
        literals = {r['annotation']['time_span']['text'] for r in rows}
        require(not sources & historical and not sources & seen and not groups & groups_seen and not literals & literal_seen,
                'historical or cross-panel source/group/time literal overlap')
        seen |= sources; groups_seen |= groups; literal_seen |= literals
        masked = [body_layout(r) for r in rows]; layouts[split] = set(masked)
        by_source = {}
        for r in rows:by_source.setdefault(r['source_sha256'],[]).append(r)
        expected = {'queries':len(rows),'sources':len(sources),'units':len({r['annotation']['unit_id'] for r in rows}),
                    'class_counts':dict(Counter(r['label'] for r in rows)),
                    'modality_by_class':{label:dict(Counter(r['annotation']['modality'] for r in rows if r['label']==label)) for label in metric.CLASSES},
                    'time_form_by_class':{label:dict(Counter(r['annotation']['time_form'] for r in rows if r['label']==label)) for label in metric.CLASSES},
                    'source_cardinality_and_distinct_owner_types':dict(Counter(f"{len(v)}occ/{len({r['label'] for r in v})}types" for v in by_source.values())),
                    'normalized_body_layouts':sorted(layouts[split]),
                    'matches_train_body_layout_queries':sum(m in layouts['train'] for m in masked),
                    'matches_train_or_tuning_body_layout_queries':sum(m in (layouts['train']|layouts.get('tuning',set())) for m in masked),
                    'source_hashes':sorted(by_source),'time_literals':sorted(literals)}
        require(wire(expected) == wire(exposure['panels'][split]), 'independent exposure reconstruction differs: '+split)
        results[split] = {k:v for k,v in expected.items() if k not in ('normalized_body_layouts','source_hashes','time_literals')}
    require(not layouts['fresh_structural'] & (layouts['train']|layouts['tuning']), 'structural holdout matches an admitted masked body')
    require(all(type(exposure[k]) is int and exposure[k] == 0 for k in
                ('historical_source_overlap','cross_split_source_overlap','cross_split_group_overlap','cross_split_literal_overlap')),
            'exposure overlap counts differ')
    require(ledger['schema'] == 'paired-temporal-ownership-reference-ledger/v1' and
            ledger['candidate_inventory_usage'] == 'reference_only_not_inference_inputs', 'reference ledger authority differs')
    for split, rows in fresh_targets.items():
        require(wire(ledger['annotations'][split]) == wire([{k:r[k] for k in ('id','source_sha256','group_id','label','annotation')} for r in rows]),
                'fresh ledger/source/label join differs')
    return {'panels':results,'historical_unique_sources_checked':len(historical),'structural_holdout_matches_admitted_body_layouts':0,
            'shared_local_attachment_grammar':True,'independent_legal_gold':False,'reference_side_candidate_audits':
            {split:reference_candidate_audit(rows) for split,rows in panels.items()}}


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
    return write(output,{'schema':'legal-paired-owner-type-independent-replay/v1','generation_freeze':freeze_pin,
                        'producer_files':producer_pins(),'replays':rows,'exact_replay':True,
                        'encoder_batch_forwards':batches,'encoder_source_evaluations':queries,
                        'fresh_references_opened':False,'fresh_reference_guard':guard,
                        'logical_aliases_are_not_reexecutions':True,'pipeline_promotion':False})


def check_replay(freeze, freeze_pin, replayed, sources, unique, counts):
    require(replayed['schema'] == 'legal-paired-owner-type-independent-replay/v1' and replayed['exact_replay'] is True and
            wire(replayed['generation_freeze']) == wire(freeze_pin) and replayed['fresh_references_opened'] is False and
            replayed['fresh_reference_guard']['released'] is False and not replayed['fresh_reference_guard']['premature_read_attempts'],
            'complete sealed independent replay must precede reference release')
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
    admitted = []; choices = {}; cache = {}; physical_rows = physical_batches = 0
    for name, trial in sorted(trials.items()):
        values = {}
        for step in STEPS:
            stage = trial['parent_candidate'] if step == 0 else next(s for s in trial['stages'] if s['steps']==step)
            kind = stage['decoder_kind']; panel_scores = {}
            for panel in ADMITTED:
                pin = stage[panel+'_generation']; saved = read(pin)
                predictions = generation(saved,stage['checkpoint'],freeze['sources'][panel],sources[panel],
                    arm='finetune_occurrence' if kind=='old_owner_type' else trial['arm'],seed=trial['seed'],
                    step=200 if kind=='old_owner_type' else step,decoder_kind=kind)
                key = digest({'generation':pin['sha256'],'sources':freeze['sources'][panel]['sha256'],'labels':labels[panel]})
                if key not in cache:
                    cache[key] = metric.score(sources[panel],predictions,labels[panel])
                    physical_rows += len(predictions); physical_batches += saved['encoder_batch_forwards']
                result = cache[key]; reconcile_metrics(result,stage[panel+'_metrics'])
                panel_scores[panel] = {k:v for k,v in result.items() if k!='rows'}
            values[step] = panel_scores
            admitted.append({'trial':name,'steps':step,'checkpoint':stage['checkpoint'],'decoder_kind':kind,'scores':panel_scores})
        choice = independent_selection(values)
        require(choice['selected_steps'] == trial['selected_steps'], 'independent admitted-tuning selection differs')
        for stage in trial['stages']:
            require(stage['eligible'] is (stage['steps'] in choice['eligible_steps']), 'saved eligibility differs from independent retention gate')
        choices[name] = choice
    require(len(cache)==80 and physical_rows==41280 and physical_batches==860,'complete parent/stage admitted score denominator differs')
    return admitted,choices,{'physical_saved_files_scored':len(cache),'physical_saved_query_rows_scored':physical_rows,
                             'logical_stage_scores':len(admitted),'logical_saved_query_rows_scored':len(admitted)*sum(COUNTS[p] for p in ADMITTED),
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
        corpus.validate_units(rows,ledger['units'][panel],panel)
        require(wire([corpus.source_row(r) for r in rows]) == wire(sources[panel]), 'fresh target/query order differs')
    annotation_audit = exposure_audit(data,targets,ledger,exposure)
    prior = read(manifest['prior_corpus']); old_ledger = read(prior['artifacts']['fresh_annotation_ledger'])
    for panel,key,split in (('old_single_fresh','single_targets','fresh'),('old_multi_fresh','multi_targets','multi_fresh')):
        rows = read(manifest['regression_references'][key]); corpus.old.validate_panel(rows,old_ledger['groups'][split],split)
        require(wire([corpus.source_row(r) for r in rows]) == wire(sources[panel]), 'exposed regression source/reference order differs')
        targets[panel] = rows
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
            for base,other in [('parent',arm) for arm in ARMS]+[('single_replay','mixed_occurrences'),('mixed_occurrences','ambiguity_weighted')]:
                left = parent if base=='parent' else selected[base]; right = selected[other]
                comparisons.append({'seed':seed,'panel':panel,'baseline':base,'arm':other,
                    **paired_comparison(physical[left['generation_key']]['metrics'],physical[right['generation_key']]['metrics'])})
    return write(output,{'schema':SCHEMA,'generation_freeze':freeze_pin,'replay_freeze':replay_pin,
        'producer_files':producer_pins(),'reference_release_after_replay_and_admitted_selection':True,'fresh_reference_guard':guard,
        'released_references':[artifacts[k] for k in runner.SEALED_KEYS],'admitted_scores':admitted,'admitted_scoring':admitted_counts,
        'independent_selection':choices,'independently_selected_steps':{k:v['selected_steps'] for k,v in choices.items()},
        'physical_evaluation_scores':physical,'logical_evaluation_scores':logical,'paired_selected_comparisons':comparisons,
        'counters':counts,'legacy_counter_names_fresh_include_exposed_regression_panels':True,
        'current_fresh_logical_query_rows':4032,'exposed_regression_logical_query_rows':4032,
        'annotation_and_exposure_audit':annotation_audit,'extra_replay_encoder_batch_forwards':replayed['encoder_batch_forwards'],
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

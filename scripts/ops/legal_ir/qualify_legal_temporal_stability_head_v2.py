#!/usr/bin/env python3
"""Versioned UTF-8 corpus commitment correction; reuse the exact original replay.

Only the historical corpus row digest encoding changes. The old qualification
source, failed scoring log, numerical replay, model outputs, gates and selection
remain frozen. No model is restored or executed by this scoring-only wrapper.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from scripts.ops.legal_ir import qualify_legal_temporal_stability_head as original

# All inference, inventory, saved-output verification and selection code remains
# the original frozen implementation, including its exact replay producer pins.
wire,digest,require,read,reference,write=(getattr(original,k) for k in ('wire','digest','require','read','reference','write'))
TRAIN,PANELS,SEEDS,ARMS,SCHEMA=(getattr(original,k) for k in ('TRAIN','PANELS','SEEDS','ARMS','SCHEMA'))
corpus,metric,runner=(getattr(original,k) for k in ('corpus','metric','runner'))
load_inputs,inventory,check_replay,score_admitted=(getattr(original,k) for k in ('load_inputs','inventory','check_replay','score_admitted'))
mask_layout,body_layout,reference_candidate_audit=(getattr(original,k) for k in ('mask_layout','body_layout','reference_candidate_audit'))
generation,physical_metadata,paired_comparison=(getattr(original,k) for k in ('generation','physical_metadata','paired_comparison'))
ORIGINAL_SOURCE_SHA256='9b1ebaaaba674d3116fa8b6fdbc258bb291faed082937d013161226cf7c3f243'


def corpus_rows_digest(value):
    """Independent frozen corpus commitment: compact sorted UTF-8 JSON."""
    encoded=json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def producer_pins():
    pins={p['path']:p for p in original.producer_pins()}
    pins[str(Path(__file__).resolve())]=reference(__file__)
    return [pins[path] for path in sorted(pins)]


def verify_correction(freeze_path,replay_path,correction_path):
    pin=reference(correction_path);repair=read(pin)
    require(repair['schema']=='legal-temporal-stability-corpus-digest-correction/v1' and
            repair['verification_change']=='historical_corpus_rows_sha256_uses_utf8_json' and
            repair['neural_replay_reused_without_reexecution'] is True and
            repair['training_model_selection_and_gates_changed'] is False and
            repair['correction_made_after_authorized_reference_release'] is True and
            repair['fresh_reference_release_already_authorized'] is True,
            'bounded versioned scoring correction required')
    require(wire(repair['generation_freeze'])==wire(reference(freeze_path)) and
            wire(repair['original_numerical_replay'])==wire(reference(replay_path)),
            'correction generation/replay binding differs')
    base=read(repair['original_implementation_freeze'])
    require(base['source']['sha256']==ORIGINAL_SOURCE_SHA256 and
            wire(base['source'])==wire(reference(original.__file__)) and
            wire(base['producer_files'])==wire(original.producer_pins()),
            'original frozen qualifier closure changed')
    for source in base['producer_files']+[base['tests']]:original.read_producer(source)
    require(wire(repair['corrected_source'])==wire(reference(__file__)) and
            wire(repair['corrected_producer_files'])==wire(producer_pins()),'corrected source closure changed')
    for source in repair['corrected_producer_files']+[repair['corrected_tests']]:original.read_producer(source)
    for key in ('failed_score_log','encoding_diagnosis','focused_test_xml','focused_test_log'):
        original.read_producer(repair[key])
    return pin


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
                            'body_layouts':sorted(layouts),'rows_sha256':corpus_rows_digest(rows)}
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


def score(freeze_path, replay_path, output, correction_path):
    correction_pin=verify_correction(freeze_path,replay_path,correction_path)
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
        'producer_files':producer_pins(),'verifier_correction':correction_pin,
        'original_numerical_replay_reused':True,'new_neural_evaluations_in_corrected_scoring':0,
        'scoring_correction_made_after_authorized_reference_release':True,
        'prior_authorized_reference_release_attempt_preserved':True,
        'reference_release_after_replay_and_admitted_selection':True,'fresh_reference_guard':guard,
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation-freeze',required=True);parser.add_argument('--replay-freeze',required=True)
    parser.add_argument('--correction',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(score(args.generation_freeze,args.replay_freeze,args.output,args.correction)),flush=True)


if __name__=='__main__':main()

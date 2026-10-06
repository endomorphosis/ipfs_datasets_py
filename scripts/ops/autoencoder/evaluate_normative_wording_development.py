#!/usr/bin/env python3
"""Source-only postfit observation of 60 prospectively sealed wordings.

All eight endpoint predictions are persisted and fsynced before this observer
parses their development references. Meanings come from exposed validation
rules; this is authored development, never independent semantic qualification.
The frozen M2 generators, fidelity scorer and full-vocabulary CE owner are used
without changing their code, masks, target limits or selection rules.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

TRAINER = 'scripts/ops/autoencoder/benchmark_normative_wording_training.py'
AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
OBSERVER = AUTO+'generated_scalar_observation.py'
OBSERVER_SHA256 = '1f1d35f7fd90df0396f3222676f2ffd11f17e2b1b2c79c0a79f1600488eb08d8'
TRACE_FALSE_FLAGS = ('qualified','admitted','proof_authority','source_semantics_verified',
    'production_checkpoint','native_family_validation_performed','lake_executed',
    'checkpoint_promoted','convergence_proven','fresh_holdout')
ARMS = ('normative-wording-zero', 'normative-wording-ce')
ROLES = ('selected', 'last-attempt')
FALSE = dict(qualified=False, admitted=False, proof_authority=False, formalized=False,
    roundtrip_ok=False, checkpoint_promoted=False, convergence_proven=False,
    lake_executed=False, fresh_holdout=False, source_semantics_verified=False,
    encoder_executed=False, training_executed=False, downloads_performed=False,
    used_for_selection=False, independent_semantic_holdout=False)
FIXED = dict(schema='normative-wording-development-plan/v1', dimensions=[384,768],
    arms=list(ARMS), roles=list(ROLES), panel_count=8, samples_per_panel=60,
    seed=1729, all_predictions_before_reference_load=True,
    predictions_fsynced_before_reference_load=True, greedy_passes_per_model=1,
    context_tokens=512, output_tokens=512, temperature=0, vocabulary_size=32,
    batch_size=8, workers=1, max_seconds_per_panel=30, max_seconds_entire_run=600,
    distribution='prospective_authored_wordings_of_previously_exposed_validation_rules',
    original_meanings_previously_exposed=True, postfit_observation_only=True,
    no_training_or_selection_from_development=True, bridge_names=[],
    source_head_trace_same_greedy_pass=True, extra_source_head_evaluations=0,
    full_vocabulary_source_recurrent_combined_logits=True,
    source_head_and_formula_join_after_reference_barrier=True,
    unvisited_source_sites_counted_correct=False, observer_sha256=OBSERVER_SHA256,
    max_trace_memory_bytes=134217728,
    legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
    cache_scope='warm authenticated source vectors; no encoder forward', **FALSE)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def bound(manifest, path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    require(manifest['inputs'].get(str(path)) == hashlib.sha256(raw).hexdigest(),
        'unbound or changed development observer input')
    return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        plan[k] == v for k,v in FIXED.items()), 'fixed development observer recipe differs')


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('normative wording development observer deadline')


def durable_save(save, path, value):
    """Persist through the established owner, then fsync file and directory."""
    reference = save(path, value)
    require(Path(reference['path']).resolve() == Path(path).resolve() and
        sha(path) == reference['sha256'], 'durable save reference differs')
    with Path(path).open('rb') as stream:
        os.fsync(stream.fileno())
    descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return reference


def restore_before_deadline(owner, lane, run, role, deadline):
    check_deadline(deadline)
    model = owner.restore_endpoint(lane, run, role)
    check_deadline(deadline)
    return model


def frozen_scalar_observer(ctx, manifest):
    """Reuse the already authenticated numerical closure without replacing it."""
    candidates = sorted(path for path,wanted in manifest['inputs'].items()
        if path.endswith('/'+OBSERVER) and wanted == OBSERVER_SHA256)
    require(candidates, 'authenticated scalar observation owner required')
    path = Path(candidates[0]).resolve()
    require(sha(path) == OBSERVER_SHA256 and
        ctx['paraphrase_manifest']['producer_pins'].get(str(path)) == OBSERVER_SHA256,
        'scalar observer source absent from frozen training closure')
    boundary = ctx['owners']['contextual_generated_boundary_training']
    fields = ctx['owners']['generated_field_training']
    require(sys.modules.get(PREFIX+'contextual_generated_boundary_training') is boundary and
        sys.modules.get(PREFIX+'generated_field_training') is fields,
        'resident scalar observer dependencies differ')
    canonical = PREFIX+'generated_scalar_observation'
    observer = sys.modules.get(canonical)
    if observer is None:
        observer = ctx['helpers'].extension(path.parents[4],OBSERVER,canonical,
            {OBSERVER:OBSERVER_SHA256})
    else:
        require(Path(observer.__file__).resolve() == path and sha(path) == OBSERVER_SHA256,
            'different scalar observer already resident')
    require(observer.boundary is boundary and observer.fields is fields and observer.core is ctx['core'],
        'scalar observer changed numerical owner identities')
    return observer


def prediction_from_trace(trace):
    """Expose the existing greedy result without a second model execution."""
    return dict(schema='normative-wording-source-predictions/v1',complete=trace['complete'],
        predictions=trace['predictions'],model_tensor_sha256=trace['model_tensor_sha256'],
        source_rows_sha256=trace['source_rows_sha256'],source_contexts_sha256=trace['source_contexts_sha256'],
        generation_reference_access=False,greedy_passes_per_row=1,generation_temperature=0,
        max_target_tokens=512,batch_size=8,elapsed_seconds=trace['elapsed_seconds'],
        same_pass_scalar_trace_sha256=trace['trace_sha256'],
        reconstructed_input_mse_measured=False,**FALSE)


def verify_predictions(records, runs, lanes, digest):
    expected = {(d,a,r) for d in FIXED['dimensions'] for a in ARMS for r in ROLES}
    require(type(records) is list and len(records) == 8 and
        {(r['dimension'],r['arm'],r['role']) for r in records} == expected,
        'all eight durable endpoint predictions required before development references')
    for record in records:
        lane = lanes[record['dimension']]
        run = runs[record['dimension'],record['arm']]
        ref = record['predictions_ref']
        require(record.get('prediction_fsynced') is True and sha(ref['path']) == ref['sha256'],
            'prediction is not unchanged and durable')
        panel = json.loads(Path(ref['path']).read_bytes())
        trace_ref = record['source_head_trace_ref']
        require(record.get('source_head_trace_fsynced') is True and sha(trace_ref['path']) == trace_ref['sha256'],
            'same-pass source-head trace is not unchanged and durable')
        trace = json.loads(Path(trace_ref['path']).read_bytes())
        require(trace.get('schema') == 'generated-contextual-scalar-trace/v1' and
            trace.get('trace_sha256') == digest({k:v for k,v in trace.items() if k != 'trace_sha256'})
            and trace.get('complete') is True and trace.get('sample_count') == 60
            and trace.get('dimension') == record['dimension'] and
            trace.get('model_tensor_sha256') == record['state_ref']['tensor_sha256']
            and trace.get('source_rows_sha256') == digest(lane['fresh_rows'])
            and trace.get('source_contexts_sha256') == digest(lane['fresh_contexts'])
            and trace.get('codec_sha256') == digest(lane['donor']['codec'])
            and trace.get('input_transform_sha256') == digest(lane['donor']['input_transform'])
            and trace.get('vocabulary_size') == 32 and trace.get('generation_temperature') == 0
            and trace.get('max_target_tokens') == 512 and trace.get('batch_size') == 8
            and trace.get('predictions') == panel.get('predictions')
            and panel.get('same_pass_scalar_trace_sha256') == trace['trace_sha256']
            and all(trace.get(k) is True for k in ('source_only','full_vocabulary_retained',
                'decomposition_exact','caller_state_preserved','hooks_removed',
                'complete_rollout_before_reference_scoring'))
            and all(trace.get(k) is False for k in ('reference_count_access','reference_prefix_access',
                'reference_documents_passed_to_model','inventory_access','source_context_target_access',
                'syntax_mask','forced_closure','model_copied',*TRACE_FALSE_FLAGS))
            and all(type(trace.get(k)) is int and trace[k] == 0 for k in
                ('extra_model_passes','source_head_extra_evaluations','optimizer_steps')),
            'source-head trace reference/generation/provenance policy differs')
        require(record['state_ref'] == run['states'][record['role']] and
            panel.get('complete') is True and panel.get('model_tensor_sha256') ==
            record['state_ref']['tensor_sha256'] and panel.get('source_rows_sha256') ==
            digest(lane['fresh_rows']) and panel.get('source_contexts_sha256') ==
            digest(lane['fresh_contexts']) and len(panel.get('predictions',[])) == 60 and
            [r['id'] for r in panel['predictions']] == [r['id'] for r in lane['fresh_rows']] and
            panel.get('generation_reference_access') is False and panel.get('greedy_passes_per_row') == 1
            and panel.get('generation_temperature') == 0 and panel.get('max_target_tokens') == 512,
            'incomplete or mismatched source-only development predictions')


def load_references(manifest, records, runs, lanes, codec, digest):
    verify_predictions(records, runs, lanes, digest)
    refs = bound(manifest, manifest['references'])
    receipt = bound(manifest, manifest['development_receipt'])
    source = [{k:r[k] for k in ('id','source_text')} for r in lanes[384]['fresh_rows']]
    require(source == [{k:r[k] for k in ('id','source_text')} for r in lanes[768]['fresh_rows']],
        'development source ordering differs by width')
    require(type(refs) is list and len(refs) == 60 and len(codec['target_vocabulary']) == 32
        and receipt.get('complete') is True and receipt.get('schema') == 'prospective-normative-development/v1'
        and receipt.get('receipt_sha256') == digest({k:v for k,v in receipt.items() if k != 'receipt_sha256'})
        and receipt.get('references_sha256') == digest(refs) and receipt.get('source_rows_sha256') == digest(source)
        and receipt.get('codec_sha256') == digest(codec)
        and receipt.get('sealed_recipe_sha256') == manifest['development_recipe_seal']
        and receipt.get('actor_action_disjointness_checked') is True
        and receipt.get('actor_action_group_overlap') == 0
        and receipt.get('original_meanings_previously_exposed') is True
        and all(receipt.get(k) is False for k in ('training_allowed','selection_allowed',
            'independent_human_review_authenticated','source_semantics_verified','admitted','qualified')),
        'authenticated authored development receipt required')
    for ref,row in zip(refs, source):
        ids = ref['target_ids']
        require(ref['id'] == row['id'] and ref['source_text'] == row['source_text']
            and ref['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
            and ref.get('split') == 'prospective_authored_development' and ref.get('clause_count') == 1
            and ref['target_sha256'] == digest(ref['target']) and ref['target_ids_sha256'] == digest(ids)
            and type(ids) is list and 3 <= len(ids) <= 512 and ids[0] == 1 and ids[-1] == 2
            and all(type(t) is int and 3 <= t < 32 for t in ids[1:-1])
            and json.loads(''.join(codec['target_vocabulary'][t] for t in ids[1:-1])) == ref['target'],
            'complete unchanged development source/target binding required')
    return refs,receipt


def scoring_references(references, receipt):
    """Add truthful grouping metadata only after the reference-access barrier."""
    require(receipt['actor_action_group_overlap'] == 0 and
        receipt['actor_action_disjointness_checked'] is True, 'checked unseen actor/action groups required')
    return [dict(deepcopy(ref), template_family=ref['template'],
        components=[dict(slot=0, training_pair_seen=False)]) for ref in references]


def join_source_heads_and_formula(scalar_score, fidelity, references):
    """Join fixed source positions; absence remains unvisited, never correct."""
    require(scalar_score.get('complete') is True and len(references) == 60 and
        len(fidelity['rows']) == 60, 'complete sixty-row paired evidence required')
    identities = {reference['id'] for reference in references}
    require(len(identities) == 60, 'unique sixty-row paired references required')
    events = {}
    for event in scalar_score['events']:
        key = (event['id'],event['slot'],event['field'])
        require(key not in events and key[0] in identities and key[1] == 0 and
            key[2] in ('actor','action','modality','object'),
            'duplicate or foreign causal scalar site cannot be collapsed')
        events[key] = event
    unvisited = {(r['id'],r['slot'],r['field']) for r in scalar_score['unvisited_reference_sites']}
    rows = []
    counts = {field:dict(reference_rows=60,visited=0,unvisited=0,source_correct=0,
        source_incorrect=0,source_correct_formula_wrong=0,source_wrong_formula_correct=0)
        for field in ('actor','action','modality','object')}
    require([row['id'] for row in fidelity['rows']] == [ref['id'] for ref in references],
        'source-head/formula reference ordering differs')
    for ref,formula in zip(references,fidelity['rows']):
        fields = {}
        for field,bucket in counts.items():
            key = (ref['id'],0,field)
            event = events.get(key)
            formula_correct = formula['by_facet'][field]['correct'] == 1
            if event is None:
                require(key in unvisited, 'missing source-head event without explicit unvisited receipt')
                bucket['unvisited'] += 1
                fields[field] = dict(status='unvisited',source_correct=None,formula_field_correct=formula_correct)
            else:
                correct = event['source']['argmax_token_id'] == event['target_token_id']
                bucket['visited'] += 1
                bucket['source_correct' if correct else 'source_incorrect'] += 1
                bucket['source_correct_formula_wrong'] += int(correct and not formula_correct)
                bucket['source_wrong_formula_correct'] += int(not correct and formula_correct)
                fields[field] = dict(status='visited',source_correct=correct,formula_field_correct=formula_correct,
                    target_token_id=event['target_token_id'],actual_next_token_id=event['actual_next_token_id'],
                    position=event['position'],source=event['source'],recurrent=event['recurrent'],combined=event['combined'])
        rows.append(dict(id=ref['id'],source_sha256=ref['source_sha256'],
            expected_ir=ref['target'],generated_ir=formula['generated_ir'],
            formula_ordered_exact=bool(formula['counts']['ordered_exact']),
            formula_syntax_valid=bool(formula['counts']['syntax_valid']),
            source_head_rule_complete=all(value['status'] == 'visited' for value in fields.values()),
            source_head_all_four_fields_correct=(all(value['source_correct'] is True for value in fields.values())
                if all(value['status'] == 'visited' for value in fields.values()) else None),
            source_head_rule_scope='four scalar fields; qualifier reconstruction is measured by full formula fidelity',
            fields=fields))
    require(all(bucket['visited']+bucket['unvisited'] == 60 and
        bucket['source_correct']+bucket['source_incorrect'] == bucket['visited'] for bucket in counts.values()),
        'fixed sixty-source head denominators differ')
    return dict(schema='normative-wording-source-head-formula-join/v1',complete=True,rows=rows,
        per_field=counts,source_head_scored_only_at_visited_available_sites=True,
        unvisited_counted_correct=False,reference_labels_applied_after_durable_barrier=True,**FALSE)


def execute(args):
    started = time.monotonic()
    deadline = started+FIXED['max_seconds_entire_run']
    manifest = json.loads(args.manifest.read_bytes())
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    manifest_sha = sha(args.manifest)
    require(plan['input_sha256'] == manifest['inputs'], 'development input seal differs')
    def recheck():
        check_deadline(deadline)
        require(sha(args.manifest) == manifest_sha and sha(args.plan) == manifest['plan_sha256'],
            'development observer seal differs')
        for path,wanted in manifest['inputs'].items():
            check_deadline(deadline)
            require(sha(path) == wanted, 'sealed development input changed')
        for relative,wanted in manifest['extensions'].items():
            check_deadline(deadline)
            require(sha(args.extension_root/relative) == wanted, 'frozen development source changed')
    recheck()
    require(not args.output.exists(), 'fresh development observer output required')
    parent = bound(manifest, manifest['training_manifest'])
    root = Path(manifest['training_extension_root'])
    require(sha(root/TRAINER) == parent['extensions'][TRAINER], 'frozen normative trainer differs')
    spec = importlib.util.spec_from_file_location('_normative_wording_training_observer', root/TRAINER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    previous = SimpleNamespace(**vars(args))
    previous.manifest = Path(manifest['training_manifest'])
    previous.plan = Path(manifest['training_plan'])
    previous.extension_root = root
    previous.dimension = 384
    ctx = runner.load_context(previous, deadline)
    before = runner.source_inventory(previous, ctx)
    scalar_observer = frozen_scalar_observer(ctx,manifest)
    runs = {}
    for dimension in FIXED['dimensions']:
        terminal = manifest['training_terminals'][str(dimension)]
        require(bound(manifest,terminal['child_exit'])['returncode'] == 0 and
            bound(manifest,terminal['resources_final'])['status'] == 'released',
            'completed released training required')
        summary = bound(manifest, manifest['training_summaries'][str(dimension)])
        require(summary['complete'] is True and summary['phase'] == 'training'
            and summary['dimension'] == dimension and len(summary['runs']) == 2
            and {r['arm'] for r in summary['runs']} == set(ARMS), 'both complete training arms required')
        for item in summary['runs']:
            run = bound(manifest,item['summary_path'])
            require(sha(item['summary_path']) == item['summary_sha256'] and run['dimension'] == dimension
                and run['arm'] == item['arm'] and run['budget_completed'] is True and run['seed'] == 1729
                and all(run[k] is False for k in ('qualified','admitted','checkpoint_promoted')),
                'training endpoint identity differs')
            for role in ROLES:
                ref = run['states'][role]
                require(manifest['inputs'].get(str(Path(ref['path']).resolve())) == ref['sha256'],
                    'endpoint must be bound before generation')
            runs[dimension,run['arm']] = run
    lanes = {}
    digest = ctx['core'].digest
    for dimension in FIXED['dimensions']:
        check_deadline(deadline)
        lane = ctx['mixture_owner'].prepare_lane(ctx,dimension)
        lane['continuation_manifest'] = manifest
        require(str(Path(manifest['source_inputs'][str(dimension)]).resolve()) not in
            {str(Path(manifest[k]).resolve()) for k in ('references','development_receipt')},
            'source and reference artifacts must be separate')
        data = bound(manifest,manifest['source_inputs'][str(dimension)])
        require(data['schema'] == 'prospective-wording-source-inputs/v1' and data['complete'] is True
            and data['dimension'] == dimension and data['inputs_sha256'] ==
            digest({k:v for k,v in data.items() if k != 'inputs_sha256'}),
            'authenticated prospective source-only cache required')
        rows = data['rows']
        require(len(rows) == 60 and all(set(r) == {'id','source_text','input'} for r in rows)
            and all(len(r['source_text'].split('\n\n')) == 1 for r in rows)
            and len(data['clause_cache']) == 60 and all(set(r) == {'id','source_text','input'}
                for r in data['clause_cache']), 'closed60 single-clause development rows required')
        for row in rows:
            ctx['core']._vector(row['input'],dimension)
        owner = ctx['owners']['clause_source_context']
        contexts = owner.build_source_contexts([{k:r[k] for k in ('id','source_text')} for r in rows],
            data['clause_cache'])
        require(contexts == data['source_contexts'] and owner.validate_contexts(rows,contexts)['dimension']
            == dimension, 'prospective source contexts differ')
        lane.update(fresh_rows=rows, fresh_contexts=contexts)
        lanes[dimension] = lane
    args.output.mkdir(parents=True)
    save = ctx['helpers'].save
    owner = ctx['exposed_evaluator']
    records = []
    durable_save(save,args.output/'sealed-recipe.json',dict(manifest=manifest,plan=plan,**FALSE))
    for dimension in FIXED['dimensions']:
        for arm in ARMS:
            run = runs[dimension,arm]
            alias = run['states']['selected']['tensor_sha256'] == run['states']['last-attempt']['tensor_sha256']
            for role in ROLES:
                lane = lanes[dimension]
                model = restore_before_deadline(ctx['mixture_owner'],lane,run,role,deadline)
                trace = scalar_observer.collect_source_scalar_trace(model,lane['fresh_rows'],
                    codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],
                    source_contexts=lane['fresh_contexts'],max_target_tokens=512,batch_size=8,
                    deadline=min(deadline,time.monotonic()+30.),max_memory_bytes=FIXED['max_trace_memory_bytes'])
                trace_ref = durable_save(save,args.output/f'{dimension}-{arm}'/(role+'-source-head-trace.json'),trace)
                panel = prediction_from_trace(trace)
                panel.update(distribution=FIXED['distribution'],original_meanings_previously_exposed=True,
                    selected_last_identical_tensor_alias=alias,**FALSE)
                ref = durable_save(save,args.output/f'{dimension}-{arm}'/(role+'-predictions.json'),panel)
                check_deadline(deadline)
                records.append(dict(dimension=dimension,arm=arm,role=role,state_ref=run['states'][role],
                    predictions_ref=ref,prediction_fsynced=True,generation_seconds=panel['elapsed_seconds'],
                    source_head_trace_ref=trace_ref,source_head_trace_fsynced=True,
                    selected_last_identical_tensor_alias=alias))
                del model,panel,trace
    durable_save(save,args.output/'predictions-complete.json',dict(complete=True,records=records,
        development_reference_json_loaded=False,all_predictions_fsynced=True,**FALSE))
    refs,receipt = load_references(manifest,records,runs,lanes,ctx['donor']['codec'],digest)
    scoring_refs = scoring_references(refs,receipt)
    results = []
    for record in records:
        lane = lanes[record['dimension']]
        run = runs[record['dimension'],record['arm']]
        model = restore_before_deadline(ctx['mixture_owner'],lane,run,record['role'],deadline)
        ref = record['predictions_ref']
        require(sha(ref['path']) == ref['sha256'], 'saved development prediction changed')
        prediction = json.loads(Path(ref['path']).read_bytes())
        trace_ref = record['source_head_trace_ref']
        require(sha(trace_ref['path']) == trace_ref['sha256'], 'saved source-head trace changed')
        trace = json.loads(Path(trace_ref['path']).read_bytes())
        remaining = min(deadline,time.monotonic()+30.-record['generation_seconds'])
        scalar_score_started = time.monotonic()
        scalar_score = scalar_observer.score_scalar_trace(trace,
            [dict(row,target_ids=reference['target_ids']) for row,reference in zip(lane['fresh_rows'],refs)],
            refs,split='exposed_development',codec=lane['donor']['codec'],
            input_transform=lane['donor']['input_transform'],source_contexts=lane['fresh_contexts'],
            validate_rule=lane['validate_rule'],deadline=remaining)
        scalar_seconds = time.monotonic()-scalar_score_started
        scalar_ref = durable_save(save,args.output/f'{record["dimension"]}-{record["arm"]}'/
            (record['role']+'-source-head-score.json'),scalar_score)
        score = owner.score_panel(ctx,lane,model,prediction,scoring_refs,
            remaining)
        score.update(original_references_sha256=digest(refs),
            grouping_metadata_added_after_reference_barrier=True,
            distribution=FIXED['distribution'],**FALSE)
        scored = durable_save(save,args.output/f'{record["dimension"]}-{record["arm"]}'/
            (record['role']+'-score.json'),score)
        check_deadline(deadline)
        fields = score['fidelity']['by_facet']
        joined = join_source_heads_and_formula(scalar_score,score['fidelity'],refs)
        joined_ref = durable_save(save,args.output/f'{record["dimension"]}-{record["arm"]}'/
            (record['role']+'-source-head-formula-join.json'),joined)
        results.append(dict(record,score_ref=scored,scoring_seconds=score['elapsed_seconds'],
            source_head_score_ref=scalar_ref,source_head_scoring_seconds=scalar_seconds,
            source_head_formula_join_ref=joined_ref,source_head_by_field=joined['per_field'],
            ordered_exact=score['fidelity']['metrics']['ordered_exact'],
            syntax_valid=score['fidelity']['metrics']['syntax_valid'],
            field_exact={field:dict(correct=fields[field]['correct'],total=fields[field]['total'])
                for field in ('actor','action','modality','object')},
            token_cross_entropy=score['teacher_forced']['token_cross_entropy']))
        del model,prediction,score,trace,scalar_score,joined
    after = runner.source_inventory(previous,ctx)
    require(all(after.get(k) == v for k,v in before.items()), 'observer producer changed')
    recheck()
    result = dict(schema='normative-wording-development-results/v1',complete=True,panels=results,
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,
        original_meanings_previously_exposed=True,references_sha256=digest(refs),
        development_receipt_sha256=digest(receipt),
        all_predictions_persisted_before_reference_load=True,
        all_predictions_fsynced_before_reference_load=True,recipe=FIXED,**FALSE)
    durable_save(save,args.output/'summary.json',result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['evaluation'],required=True)
    execute(parser.parse_args())


if __name__ == '__main__':
    main()

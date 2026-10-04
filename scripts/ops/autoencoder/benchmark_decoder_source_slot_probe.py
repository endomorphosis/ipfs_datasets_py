#!/usr/bin/env python3
"""Train-only linear probes of frozen Legal source features; no formula decoding."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
STATES=['selected-common','unchanged-1729-last','ramp20-1729-last','unchanged-2718-last','ramp20-2718-last']
FEATURES=['projected-shared']+['conditioning-'+s for s in STATES]+['intercept']
CONTROLS=['conditioned','source_shuffle','cross_length_shuffle','zero_features']
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False,decoder_training_executed=False,encoder_training_executed=False,
    formula_generation_executed=False,validation_tuning=False,selection_performed=False)
FIXED=dict(schema='decoder-source-slot-probe-plan/v1',representation_dimension=384,state_order=STATES,
    feature_order=FEATURES,split_order=['train','validation'],control_order=CONTROLS,
    expected_feature_variants=7,expected_panels=56,expected_rows_per_panel=48,max_rule_slots=8,
    fields=['actor','action','modality','object'],count_classes=list(range(1,9)),ridge_lambda=.001,
    epochs_per_source_stage=20,fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,
    max_seconds_per_operation=30,max_memory_bytes_per_operation=536870912,feature_batch_size=48,
    decoder_training_executed=False,probe_fitting_executed=True,optimizer_steps=0,
    new_formula_generation_allowed=False,no_downloads=True,temperature=0,strict_gates_changed=False,
    validation_tuning=False,selection_performed=False,raw_feature_and_probe_arrays_retained=True)


def require(condition,message):
    if not condition:
        raise ValueError(message)


def validate_plan(plan):
    require(type(plan) is dict,'explicit probe plan required')
    for key,value in FIXED.items():
        require(json.dumps(plan.get(key),sort_keys=True,allow_nan=False)==json.dumps(value,sort_keys=True,allow_nan=False),
            'fixed probe recipe differs: '+key)


def load_helper(root,pins,relative,name):
    path=root/relative
    require(hashlib.sha256(path.read_bytes()).hexdigest()==pins.get(relative),'frozen helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def control_features(rows,references,kind):
    """Negative controls change feature assignments only; prediction gets no labels."""
    require(kind in CONTROLS,'unknown feature control')
    ids=[r['id'] for r in rows];by_id={r['id']:r for r in rows}
    by_ref={r['id']:r for r in references}
    require(len(ids)==len(by_id)==len(by_ref)==len(references) and set(ids)==set(by_ref),'control reference identity differs')
    assignment={i:i for i in ids}
    if kind=='source_shuffle':
        for count in sorted({r['clause_count'] for r in references}):
            group=sorted(i for i in ids if by_ref[i]['clause_count']==count)
            require(len(group)>1,'within-length control requires nontrivial bins')
            assignment.update({i:group[(n+1)%len(group)] for n,i in enumerate(group)})
    elif kind=='cross_length_shuffle':
        groups={k:sorted(i for i in ids if by_ref[i]['clause_count']==k) for k in (1,2,4,8)}
        require(len(ids)==48 and all(len(v)==12 for v in groups.values()),'cross-length control requires fixed balanced48panel')
        order=[i for group in groups.values() for i in group]
        assignment={i:order[(n+12)%48] for n,i in enumerate(order)}
        require(all(by_ref[i]['clause_count']!=by_ref[j]['clause_count'] for i,j in assignment.items()),'cross-length control preserved a count')
    actual=[{**row,'features':list(by_id[assignment[row['id']]]['features'])} for row in rows]
    return actual,dict(kind=kind,source_assignment=assignment)


def extract_features(model,source_rows,*,transform,core,gradient_digest,max_seconds=30.):
    """Extract projected384 and actual initial32+persistent16 conditioning.

    Input rows carry identities and source vectors only. Targets, count labels,
    prefix tokens and source text are excluded from this interface entirely.
    """
    started=time.monotonic()
    require(type(max_seconds) in (int,float) and math.isfinite(max_seconds) and 0<max_seconds<=30,'bounded extraction deadline required')
    def check():
        if time.monotonic()-started>max_seconds:raise TimeoutError('feature extraction deadline exceeded')
    torch=core._torch()
    require(type(source_rows) is list and 1<=len(source_rows)<=48,'bounded source-only inventory required')
    require(all(type(r) is dict and set(r)=={'id','source_sha256','input'} and type(r['id']) is str
        and type(r['source_sha256']) is str and core._SHA.fullmatch(r['source_sha256'])
        and type(r['input']) is list and len(r['input'])==384
        and all(type(v) in (int,float) and math.isfinite(v) for v in r['input']) for r in source_rows),
        'closed finite source-only rows required')
    require(len({r['id'] for r in source_rows})==len(source_rows),'duplicate source identity')
    require(model.dimension==384 and model.describe()['schema']=='source-cardinality-decoder-development/v1',
        'original384D cardinality state required')
    require(type(transform) is dict and set(transform)=={'mode','mean','scale','origin'}
        and transform['origin']=='training_only' and transform['mode'] in ('none','center_rms')
        and type(transform['mean']) is list and len(transform['mean'])==384
        and all(type(v) in (int,float) and math.isfinite(v) for v in transform['mean'])
        and type(transform['scale']) in (int,float) and math.isfinite(transform['scale']) and transform['scale']>0,
        'explicit inherited input transform required')
    before=core.tensor_digest(model);grad=gradient_digest(model)
    modes={n:m.training for n,m in model.named_modules()}
    trainable={n:p.requires_grad for n,p in model.named_parameters()}
    input_digest=core.digest(source_rows);transform_digest=core.digest(transform)
    rng=torch.get_rng_state().clone();py_rng=random.getstate()
    try:
        working=deepcopy(model);working.eval();check()
        with torch.inference_mode():
            raw=torch.tensor([r['input'] for r in source_rows],dtype=torch.float32)
            values=(raw-torch.tensor(transform['mean'],dtype=torch.float32))/transform['scale']
            projected=working.project(values)
            hidden=working.body.start(projected)[0].squeeze(0)
            persistent=working.body.source_to_embedding(projected)
            require(tuple(projected.shape)==(len(source_rows),384) and tuple(hidden.shape)==(len(source_rows),32)
                and tuple(persistent.shape)==(len(source_rows),16),'actual source feature geometry differs')
            condition=torch.cat((hidden,persistent),dim=1)
            require(core._finite(torch,projected) and core._finite(torch,condition),'nonfinite source features')
            arrays={'projected_source':projected.tolist(),'conditioning':condition.tolist()}
            rows={kind:[dict(id=r['id'],source_sha256=r['source_sha256'],features=v)
                for r,v in zip(source_rows,array)] for kind,array in arrays.items()}
        check()
    finally:
        rng_unchanged=torch.equal(rng,torch.get_rng_state()) and py_rng==random.getstate()
        torch.set_rng_state(rng);random.setstate(py_rng)
        require(core.tensor_digest(model)==before and gradient_digest(model)==grad
            and modes=={n:m.training for n,m in model.named_modules()}
            and trainable=={n:p.requires_grad for n,p in model.named_parameters()}
            and core.digest(source_rows)==input_digest and core.digest(transform)==transform_digest
            and rng_unchanged,'extraction changed caller state or consumed RNG')
    check()
    return dict(rows=rows,report=dict(complete=True,model_weights_sha256=before,
        source_rows_sha256=input_digest,input_transform_sha256=transform_digest,
        feature_rows_sha256={kind:core.digest(value) for kind,value in rows.items()},
        feature_dimensions={'projected_source':384,'conditioning':48},
        conditioning_layout=['initial_hidden32','persistent_source_residual16'],
        reference_access=False,count_label_access=False,prefix_access=False,
        decoder_recurrent_forward_executed=False,model_changed=False,caller_rng_changed=False,
        sample_count=len(source_rows),elapsed_seconds=time.monotonic()-started,**FALSE))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();manifest=json.loads(args.manifest.read_bytes())
    replay=load_helper(args.extension_root,manifest['extensions'],'scripts/ops/autoencoder/decoder_fidelity_replay.py','_slot_replay')
    parent=load_helper(args.extension_root,manifest['extensions'],'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py','_slot_parent')
    ctx=replay.load_context(args,validate_plan=validate_plan)
    helpers,core,plan=ctx['helpers'],ctx['core'],ctx['plan'];save=helpers.save
    count=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    gradient=helpers.extension(args.extension_root,AUTO+'decoder_gradient_replay.py',PREFIX+'decoder_gradient_replay',ctx['pins'])
    owner=helpers.extension(args.extension_root,AUTO+'decoder_source_slot_probe.py',PREFIX+'decoder_source_slot_probe',ctx['pins'])
    published,runs,baseline_dedup=parent.authenticate_predecessor(manifest)
    sources_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,tree_pin=ctx['tree'],selected_baseline_deduplication=baseline_dedup,**FALSE))
    started=time.monotonic();variants={};extractions=[];projected_checks=[]
    for catalog in manifest['state_catalog']:
        state=parent.read_bound(catalog['state_path'],manifest,published)
        parent.validate_export(state,catalog,runs[catalog['prior_arm']],core,ctx['donor']['codec'])
        persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
        for name,parameter in persistent.named_parameters():
            if name.startswith(('body.projection_down.','body.projection_up.')):parameter.requires_grad_(False)
        model=count.bind_cardinality_model(persistent,codec=ctx['donor']['codec'],guide_boundary=False)
        require(model.describe()==state['architecture'] and set(model.state_dict())==set(state['model_state']),
            'private state architecture or tensor inventory differs')
        model.load_state_dict({k:ctx['numerical']._tensor(state['model_state'][k],v,k)
            for k,v in model.state_dict().items()},strict=True)
        require(core.tensor_digest(model)==state['tensor_sha256'],'private state reload differs')
        conditioning={};projected={}
        for split in plan['split_order']:
            raw=[dict(id=r['id'],source_sha256=hashlib.sha256(r['source_text'].encode()).hexdigest(),input=r['input']) for r in ctx['rows'][split]]
            value=extract_features(model,raw,transform=ctx['donor']['input_transform'],core=core,
                gradient_digest=gradient.gradient_digest,max_seconds=plan['max_seconds_per_operation'])
            projected[split]=value['rows']['projected_source'];conditioning[split]=value['rows']['conditioning']
            receipt=save(args.output/'features'/catalog['name']/(split+'.json'),value)
            extractions.append(dict(state=catalog['name'],split=split,artifact=receipt,report=value['report'],
                state_path=catalog['state_path'],state_file_sha256=manifest['inputs'][catalog['state_path']]))
        if not variants:
            variants['projected-shared']=dict(rows=projected,kind='projected_source',dimension=384,source_states=STATES)
        require(projected==variants['projected-shared']['rows']
            and core.digest(projected)==core.digest(variants['projected-shared']['rows']),
            'frozen projected features differ across source states')
        projected_checks.append(dict(state=catalog['name'],rows_sha256=core.digest(projected)))
        variants['conditioning-'+catalog['name']]=dict(rows=conditioning,kind='conditioning',dimension=48,source_states=[catalog['name']])
    variants['intercept']=dict(rows={split:[{**r,'features':[]} for r in variants['projected-shared']['rows'][split]]
        for split in plan['split_order']},kind='intercept',dimension=0,source_states=[])
    require(list(variants)==FEATURES,'feature inventory differs')
    fits=[];panels=[]
    for name,value in variants.items():
        specification=dict(id=name,kind=value['kind'],dimension=value['dimension'],provenance=dict(
            parent_public_manifest_sha256=manifest['inputs'][manifest['parent_public_manifest']],source_states=value['source_states'],
            feature_rows_sha256={split:core.digest(rows) for split,rows in value['rows'].items()}))
        features_receipt=save(args.output/name/'features.json',dict(specification=specification,rows=value['rows'],**FALSE))
        fit_started=time.monotonic()
        fit=owner.fit_probe(value['rows']['train'],ctx['references']['train'],feature_specification=specification,
            validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],ridge_lambda=plan['ridge_lambda'],
            max_seconds=plan['max_seconds_per_operation'],max_memory_bytes=plan['max_memory_bytes_per_operation'])
        require(fit['report']['complete'],'incomplete probe fit')
        fit_receipt=save(args.output/name/'fit.json',fit);probe_digest=core.digest(fit['probe'])
        fits.append(dict(feature=name,features_artifact=features_receipt,fit_artifact=fit_receipt,report=fit['report'],
            wall_seconds_including_write=time.monotonic()-fit_started))
        for split in plan['split_order']:
            for kind in CONTROLS:
                panel_started=time.monotonic()
                actual,control=control_features(value['rows'][split],ctx['references'][split],kind)
                result=owner.evaluate_probe(fit['probe'],actual,ctx['references'][split],source_features=value['rows'][split],
                    control=control,validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],
                    max_seconds=plan['max_seconds_per_operation'],max_memory_bytes=plan['max_memory_bytes_per_operation'])
                require(result['report']['complete'] and len(result['rows'])==48,'incomplete probe evaluation')
                require(core.digest(fit['probe'])==probe_digest,'evaluation changed fitted probe')
                receipt=save(args.output/name/split/(kind+'.json'),result)
                panels.append(dict(feature=name,split=split,control=kind,artifact=receipt,report=result['report'],
                    wall_seconds_including_write=time.monotonic()-panel_started))
        print(json.dumps(dict(feature=name,fit_seconds=fits[-1]['wall_seconds_including_write'],panels=8,complete=True)),flush=True)
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k)==v for k,v in sources_before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(manifest)
    for path,digest in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==digest,'frozen extension changed')
    require(helpers.sha(args.plan)==manifest['plan_sha256'],'sealed plan changed')
    require(len(fits)==7 and len(panels)==56,'probe comparison inventory differs')
    save(args.output/'summary.json',dict(schema='decoder-source-slot-probe-comparison/v1',complete=True,fits=fits,panels=panels,
        extractions=extractions,projected_feature_equivalence=projected_checks,selected_baseline_deduplication=baseline_dedup,
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,
        timing_scope='state reconstruction, source-only extraction, seven probe fits,56panels and artifact writes; excludes imports/preparation/finalsummarywrite',
        dimensions_diagnosed=[384],probe_fitting_executed=True,optimizer_steps=0,workers=1,bridge_names=[],
        legal_ir_evaluate_provers=False,metric_disk_cache_used=False,paragraph_embedding_cache_used=True,
        encoder_executed=False,encoder_context_changed=False,output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()

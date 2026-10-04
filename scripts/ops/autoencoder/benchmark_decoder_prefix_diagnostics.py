#!/usr/bin/env python3
"""Authenticated, fixed-state source-value diagnostics; no training or generation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, fresh_holdout=False,
    lake_executed=False, formalized=False, roundtrip_ok=False)
ARMS = ['unchanged-1729', 'ramp20-1729', 'unchanged-2718', 'ramp20-2718']
STATES = ['selected-common'] + [name+'-last' for name in ARMS]
LABELS = {'train/conditioned':'training', 'train/source_shuffle':'training-source-shuffle',
    'validation/conditioned':'validation', 'validation/source_shuffle':'source-shuffle',
    'validation/zero_condition':'zero-condition'}
FIXED = dict(schema='decoder-prefix-diagnostics-plan/v1', representation_dimension=384,
    state_order=STATES, split_order=['train','validation'],
    control_order=['conditioned','source_shuffle','zero_condition'], expected_panels=30,
    expected_rows_per_panel=48, expected_prediction_positions_per_panel=6228,
    expected_semantic_value_positions_per_panel=720, expected_rule_boundary_positions_per_panel=180,
    expected_eos_positions_per_panel=48, expected_archived_generation_panels=25,
    expected_unavailable_generation_panels=5, epochs_per_source_stage=20,
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, batch_size=8,
    max_seconds_per_panel=30, max_memory_bytes_per_panel=536870912,
    training_executed=False, new_generation_allowed=False, optimizer_steps=0,
    no_downloads=True, temperature=0, strict_gates_changed=False, raw_logits_retained=True)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_plan(plan):
    require(type(plan) is dict, 'explicit fixed-state diagnostic plan required')
    for key, value in FIXED.items():
        require(json.dumps(plan.get(key),sort_keys=True,allow_nan=False)==
            json.dumps(value,sort_keys=True,allow_nan=False), 'fixed diagnostic recipe differs: '+key)


def read_bound(path, manifest, published=None):
    """Match original artifact bytes to input pins and the published archive index.

    The published index itself must be authenticated against the pinned Git
    commit by the freeze step; consistency with an arbitrary index is not trust.
    """
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(manifest['inputs'].get(str(path)) == digest, 'unpinned or changed input: '+str(path))
    if published is not None:
        member = published['original_artifact_archive_paths'].get(str(path))
        require(member is not None and published['members'].get(member)==dict(sha256=digest,bytes=len(raw)),
            'input differs from published predecessor: '+str(path))
    return json.loads(raw)


def authenticate_predecessor(manifest):
    published = read_bound(manifest['parent_public_manifest'],manifest)
    public_results = read_bound(manifest['parent_public_results'],manifest)
    require(published['archive']==public_results['archive'], 'parent archive receipts disagree')
    summary = read_bound(manifest['parent_summary'],manifest,published)
    require(summary.get('complete') is True and all(summary.get(k) is False for k in FALSE),
        'complete nonqualifying predecessor required')
    runs = {run['arm']:run for run in summary['runs']}
    require(len(summary['runs'])==len(runs)==4 and set(runs)==set(ARMS), 'parent arm inventory differs')
    root = Path(manifest['parent_summary']).parent
    expected = []
    for name,arm,role in [('selected-common',ARMS[0],'selected')]+[(a+'-last',a,'last-attempt') for a in ARMS]:
        expected.append(dict(name=name,prior_arm=arm,role=role,state_path=str(root/arm/(role+'-state.json')),
            archived_evaluations={key:str(root/arm/role/('evaluation-'+label+'.json')) for key,label in LABELS.items()}))
    require(manifest['state_catalog']==expected, 'state catalog differs from exact predecessor roles')
    selected_paths = [str(root/arm/'selected-state.json') for arm in ARMS]
    require(manifest['selected_state_equivalence_paths']==selected_paths, 'selected-state equivalence inventory differs')
    selected = [read_bound(path,manifest,published) for path in selected_paths]
    require(all(runs[a]['training']['selected_epoch']==0 for a in ARMS), 'common baseline is not epoch zero')
    require(all(s['role']=='selected' and s['selected'] is True for s in selected), 'selected role differs')
    require(all(s['model_state']==selected[0]['model_state'] and s['tensor_sha256']==selected[0]['tensor_sha256']
        and s['weights_sha256']==selected[0]['weights_sha256'] for s in selected), 'selected baseline states differ')
    require(all(s['tensor_sha256']==runs[a]['training']['selected_weights_sha256']
        for a,s in zip(ARMS,selected)), 'selected states differ from parent training reports')
    return published,runs,dict(selected_epoch=0,source_state_count=4,executed_state_count=1,
        source_paths=selected_paths,tensor_sha256=selected[0]['tensor_sha256'],
        reason='all four selected epoch-zero numeric states are identical; diagnostic executed once')


def validate_export(value, catalog, run, core, codec):
    require(value.get('schema')=='private-transition-ramp-state/v1'
        and value.get('role')==catalog['role'] and value.get('selected') is (catalog['role']=='selected')
        and value.get('optimizer_resumable') is False and all(value.get(k) is False for k in FALSE),
        'private state role or authority differs')
    require(value['codec']==codec and core.digest(value['model_state'])==value['weights_sha256'],
        'private state codec or JSON weights differ')
    key='selected_weights_sha256' if catalog['role']=='selected' else 'last_complete_attempt_weights_sha256'
    require(value['tensor_sha256']==run['training'][key], 'state tensor digest differs from parent role')


def archive_for_panel(catalog, split, control, rows, manifest, published, core, codec, transform):
    provenance = dict(schema='decoder-prefix-archive/v1',split=split,rows_sha256=core.digest(rows),
        control_sha256=core.digest(control),output_limit=512)
    key=split+'/'+control['kind']
    if key not in catalog['archived_evaluations']:
        require(key=='train/zero_condition', 'unexpected absent archive panel')
        return None,{**provenance,'status':'unavailable','reason':'training-zero readout was not generated in predecessor'},None
    path=catalog['archived_evaluations'][key]
    archived=read_bound(path,manifest,published)
    report=archived['report']
    fixed=dict(complete=True,input_dimension=384,max_target_tokens=512,batch_size=8,
        generation_temperature=0,generation_target_access=False,optimizer_steps=0,weight_selection_performed=False,
        validation_rows_sha256=core.digest(rows),codec_sha256=core.digest(codec),
        input_transform_sha256=core.digest(transform),**{k:v for k,v in FALSE.items() if k in report})
    require(all(type(report.get(k)) is type(v) and report.get(k)==v for k,v in fixed.items()),
        'archived numerical readout differs from panel')
    require({k:archived['execution'][k] for k in ('kind','source_assignment')}==control,
        'archived source control differs')
    return archived['predictions'],{**provenance,'status':'available',
        'predictions_sha256':core.digest(archived['predictions']), 'prior_report_sha256':manifest['inputs'][path],
        'executed_model_weights_sha256':report['model_weights_sha256'],'codec_sha256':core.digest(codec)},report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_bytes())
    relative='scripts/ops/autoencoder/decoder_fidelity_replay.py'
    helper=args.extension_root/relative
    require(hashlib.sha256(helper.read_bytes()).hexdigest()==manifest['extensions'].get(relative),'frozen replay helper differs')
    spec=importlib.util.spec_from_file_location('_prefix_replay',helper)
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    ctx=replay.load_context(args,validate_plan=validate_plan)
    helpers,core,plan=ctx['helpers'],ctx['core'],ctx['plan']
    save=helpers.save
    count=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'decoder_gradient_replay.py',PREFIX+'decoder_gradient_replay',ctx['pins'])
    owner=helpers.extension(args.extension_root,AUTO+'decoder_prefix_diagnostics.py',PREFIX+'decoder_prefix_diagnostics',ctx['pins'])
    published,runs,dedup=authenticate_predecessor(manifest)
    source_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,tree_pin=ctx['tree'],selected_baseline_deduplication=dedup,**FALSE))
    panels=[]
    started=time.monotonic()
    for catalog in manifest['state_catalog']:
        state=read_bound(catalog['state_path'],manifest,published)
        validate_export(state,catalog,runs[catalog['prior_arm']],core,ctx['donor']['codec'])
        persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
        for name,parameter in persistent.named_parameters():
            if name.startswith(('body.projection_down.','body.projection_up.')):
                parameter.requires_grad_(False)
        model=count.bind_cardinality_model(persistent,codec=ctx['donor']['codec'],guide_boundary=False)
        require(model.describe()==state['architecture'],'private state architecture differs')
        require(set(state['model_state'])==set(model.state_dict()),'private state tensor inventory differs')
        model.load_state_dict({k:ctx['numerical']._tensor(state['model_state'][k],v,k)
            for k,v in model.state_dict().items()},strict=True)
        require(core.tensor_digest(model)==state['tensor_sha256'],'private reload tensor digest differs')
        for split in plan['split_order']:
            for kind in plan['control_order']:
                panel_started=time.monotonic()
                rows=ctx['rows'][split]
                control=dict(kind=kind,source_assignment={r['id']:r['id'] for r in rows})
                if kind=='source_shuffle':
                    rows,execution=helpers.shuffle_inputs(rows,ctx['references'][split])
                    control={k:execution[k] for k in ('kind','source_assignment')}
                predictions,archive,old_report=archive_for_panel(catalog,split,control,rows,manifest,published,
                    core,ctx['donor']['codec'],ctx['donor']['input_transform'])
                value=owner.diagnose_prefixes(model,rows,ctx['references'][split],codec=ctx['donor']['codec'],
                    input_transform=ctx['donor']['input_transform'],lineage=state['lineage'],
                    archived_predictions=predictions,archive_provenance=archive,source_rows=ctx['rows'][split],
                    control=control,validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],
                    max_target_tokens=512,batch_size=8,max_seconds=plan['max_seconds_per_panel'],
                    max_memory_bytes=plan['max_memory_bytes_per_panel'])
                report=value['report']
                require(report['complete'] and len(value['rows'])==48 and report['numerical']['target_token_count']==6228,
                    'incomplete diagnostic panel')
                positions=[p for r in value['rows'] for p in r['positions']]
                require(sum(p['meaningful_value'] for p in positions)==720
                    and sum(len(r['boundaries']) for r in value['rows'])==180
                    and sum(p['kind']=='eos' for p in positions)==48,'diagnostic positions differ from full panel')
                require(core.tensor_digest(model)==state['tensor_sha256'],'diagnostic mutated original state')
                delta=None
                if old_report is not None:
                    delta=report['numerical']['token_cross_entropy']-old_report['metrics']['token_cross_entropy']
                    require(delta==0.,'native CE differs from archived fixed-state evaluation')
                receipt=save(args.output/catalog['name']/split/(kind+'.json'),value)
                panel=dict(state=catalog['name'],split=split,control=kind,artifact=receipt,report=report,
                    state_path=catalog['state_path'],state_file_sha256=manifest['inputs'][catalog['state_path']],
                    archive_authentication='pinned published predecessor member SHA256 and byte count' if old_report else 'unavailable',
                    archived_native_ce_delta=delta,wall_seconds_including_write=time.monotonic()-panel_started)
                panels.append(panel)
                print(json.dumps(dict(state=catalog['name'],split=split,control=kind,
                    ce=report['numerical']['token_cross_entropy'],archived_ce_delta=delta,
                    bytes=receipt['bytes'],seconds=panel['wall_seconds_including_write'])),flush=True)
                del value,positions
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(path)==expected for path,expected in source_before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(manifest)
    for path,expected in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==expected,'frozen extension changed')
    require(helpers.sha(args.plan)==manifest['plan_sha256'],'sealed plan changed')
    available=sum(p['report']['archive_provenance']['status']=='available' for p in panels)
    require(len(panels)==30 and available==25,'diagnostic panel inventory differs')
    save(args.output/'summary.json',dict(schema='decoder-prefix-diagnostic-comparison/v1',complete=True,panels=panels,
        selected_baseline_deduplication=dedup,source_dependencies=after,elapsed_seconds=time.monotonic()-started,
        timing_scope='five-state construction and30prefix diagnostics including raw file writes; excludes imports/preparation and final summary write',
        dimensions_diagnosed=[384],training_executed=False,generation_executed=False,optimizer_steps=0,
        archive_panels_available=available,archive_panels_unavailable=5,workers=1,bridge_names=[],
        legal_ir_evaluate_provers=False,metric_disk_cache_used=False,paragraph_embedding_cache_used=True,
        encoder_executed=False,encoder_context_changed=False,output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()

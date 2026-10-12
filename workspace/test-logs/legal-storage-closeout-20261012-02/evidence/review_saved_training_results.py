"""Validate saved attempt03 JSON with stdlib only; never restore a model."""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
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

B = Path('/home/barberb/lift_coding')
N = B/'artifacts/legal-storage-closeout-20261012-02'
T = B/'artifacts/legal-temporal-binding-20261012-01'
R = B/'external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261012-03/results'
REVIEW = N/'result-independent-review-v01.json'
ANALYSIS = N/'training-result-analysis-v01.json'
FIELDS = ('actor','action','object','conditions','exceptions','temporal')
FALSE = dict(qualified=False,admitted=False,formalized=False,proof_authority=False,
             semantic_correctness_verified=False,promotion_performed=False)
BASE_FALSE = {**FALSE,'roundtrip_ok':False,'publication_performed':False}


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:
        raise AssertionError('No numerical imports')
    if event.startswith(('subprocess.','socket.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock'}:
        raise AssertionError('No runtime/resource operations')
    if event == 'open':
        path, mode, flags = args
        write = isinstance(mode,str) and any(c in mode for c in 'wax+')
        write |= isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write:
            require(isinstance(path,(str,bytes,os.PathLike)) and Path(os.fsdecode(path)).absolute() in {REVIEW,ANALYSIS}, 'Only two exclusive audit receipts may be written')


sys.dont_write_bytecode = True
sys.addaudithook(audit)


def wire(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def pin(path):
    path=Path(path)
    require(path.is_absolute(),'Absolute path')
    for part in (*reversed(path.parents),path):
        s=part.lstat()
        require(not stat.S_ISLNK(s.st_mode),'No symlink')
        require(stat.S_ISREG(s.st_mode) if part==path else stat.S_ISDIR(s.st_mode),'Ordinary path')
    with path.open('rb') as f:
        before=os.fstat(f.fileno());h=hashlib.sha256();count=0
        for block in iter(lambda:f.read(1048576),b''):
            h.update(block);count+=len(block)
        after=os.fstat(f.fileno())
    now=path.lstat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after)==identity(now),'Stable raw file')
    return dict(bytes=count,sha256=h.hexdigest())


def read(path):
    require(path.stat().st_size<=128*1024*1024,'Bounded JSON')
    def unique(items):
        d={}
        for k,v in items:
            require(k not in d,'Duplicate JSON key');d[k]=v
        return d
    def reject(value):
        raise ValueError('Nonfinite constant '+value)
    d=json.loads(path.read_bytes(),object_pairs_hook=unique,parse_constant=reject)
    def finite(v):
        if type(v) is float:require(math.isfinite(v),'Finite JSON number')
        elif type(v) is list:
            for x in v:finite(x)
        elif type(v) is dict:
            for x in v.values():finite(x)
    finite(d)
    return d


def f32(v):
    require(type(v) in (int,float) and math.isfinite(v),'Finite scalar')
    v=struct.unpack('!f',struct.pack('!f',v))[0]
    require(math.isfinite(v),'Finite float32')
    return v


def false_flags(value, flags=FALSE):
    require(all(value.get(k) is v for k,v in flags.items()),'Authority flags must remain false')


def strict_rule(ir):
    require(type(ir) is dict and set(ir)=={'rules'} and type(ir['rules']) is list and len(ir['rules'])==1,'Single typed rule')
    rule=ir['rules'][0]
    require(type(rule) is dict and set(rule)=={'modality',*FIELDS} and rule['modality'] in ('O','P','F'),'Closed canonical rule')
    for field in FIELDS:
        value=rule[field]
        if field in FIELDS[3:]:
            require(type(value) is list and len(value)<=1 and all(type(x) is str and x.strip() for x in value),'Copied single qualifier')
        else:
            require(type(value) is str and (field=='object' or value.strip()),'Copied actor/action/object')
    return rule


def tokenization(source):
    require(type(source) is str and source.strip() and len(source)<=16384,'Bounded source')
    values=[dict(text=m.group(),start=m.start(),end=m.end()) for m in re.finditer(r'\w+|[^\w\s]',source,re.UNICODE)]
    require(0<len(values)<=256 and all(len(x['text'].casefold().encode())<=2048 for x in values),'Bounded exact tokens')
    return values


def detached_functions(path, names, namespace):
    """Compile only named stdlib predicates, not the enclosing module."""
    tree=ast.parse(path.read_text())
    selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in selected}==set(names),'Exact detached predicate set')
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def schedule(rows):
    epoch=cursor=0;batches=[]
    for _ in range(32):
        order=list(range(len(rows)));random.Random(1729+epoch).shuffle(order)
        indices=order[cursor:cursor+12];batches.append([rows[x]['id'] for x in indices]);cursor+=len(indices)
        if cursor==len(rows):epoch+=1;cursor=0
    return dict(batch_ids=batches,batch_ids_sha256=digest(batches),final_progress=dict(epochs_completed=epoch,row_cursor=cursor,optimizer_steps=32))


def tensor(value, shape, nonnegative=False):
    if shape:
        require(type(value) is list and len(value)==shape[0],'Serialized tensor shape')
        for v in value:tensor(v,shape[1:],nonnegative)
    else:
        require(type(value) is float and math.isfinite(value) and f32(value)==value,'Exact finite serialized float32')
        require(not nonnegative or value>=0,'Nonnegative Adam variance')


def serialized_base(base, implementation):
    require(set(base)=={'schema','lineage_id','config','implementation','training_manifest_sha256','training_count','tuning_manifest_sha256','tuning_count','model_state','optimizer_state','progress','parent_checkpoint_sha256',*BASE_FALSE},'Closed base checkpoint')
    require(base['schema']=='span-legal-formula-checkpoint/v1' and base['lineage_id']=='source_span_formula_v1' and base['implementation']==implementation,'Base serialization identity')
    false_flags(base,BASE_FALSE);c=base['config'];require(c['latent_dimension']==384 and c['latent_enabled'] is False and c['device']=='cpu' and c['dtype']=='float32' and c['seed']==1729 and c['batch_size']==12 and c['learning_rate']==.001,'Dormant384 config')
    e,h,p=c['embedding_dim'],c['hidden_size'],c['projection_width'];require((e,h,p)==(16,32,16),'Frozen architecture widths')
    shapes={'byte_embedding.weight':(257,e),'token_projection.weight':(2*e,3*e+1),'token_projection.bias':(2*e,),
            'modality.weight':(3,2*h),'modality.bias':(3,),'presence.weight':(8,2*h),'presence.bias':(8,),
            'start.weight':(6,2*h),'start.bias':(6,),'end.weight':(6,2*h),'end.bias':(6,),
            'latent_down.weight':(p,384),'latent_down.bias':(p,),'latent_up.weight':(2*h,p),'latent_up.bias':(2*h,)}
    for suffix in ('','_reverse'):
        shapes.update({f'encoder.weight_ih_l0{suffix}':(3*h,2*e),f'encoder.weight_hh_l0{suffix}':(3*h,h),f'encoder.bias_ih_l0{suffix}':(3*h,),f'encoder.bias_hh_l0{suffix}':(3*h,)})
    require(set(base['model_state'])==set(shapes),'23 model tensor names')
    for k,s in shapes.items():tensor(base['model_state'][k],s)
    progress=base['progress'];require(set(progress)=={'epochs_completed','row_cursor','optimizer_steps'} and all(type(v) is int and v>=0 for v in progress.values()),'Progress contract')
    require(progress['row_cursor']<base['training_count'] and progress['row_cursor']%12==0 and progress['optimizer_steps']==progress['epochs_completed']*math.ceil(base['training_count']/12)+progress['row_cursor']//12,'Progress/cursor identity')
    optimizer=base['optimizer_state'];require(set(optimizer)=={'schema','parameters'} and optimizer['schema']=='adam-default-betas-eps/v1','Adam contract')
    require(set(optimizer['parameters'])==(set(shapes) if progress['optimizer_steps'] else set()),'Optimizer parameter coverage')
    for k,v in optimizer['parameters'].items():
        require(set(v)=={'step','exp_avg','exp_avg_sq'} and type(v['step']) is int and v['step']==progress['optimizer_steps'],'Per-parameter Adam step')
        tensor(v['exp_avg'],shapes[k]);tensor(v['exp_avg_sq'],shapes[k],True)
    return shapes


def main():
    require(not REVIEW.exists() and not ANALYSIS.exists(),'Exclusive new receipts')
    paths=sorted(R.rglob('*'));require(len(paths)<=1024 and all(not p.is_symlink() for p in paths),'Bounded result tree')
    files=[p for p in paths if p.is_file()];require(all(p.suffix=='.json' for p in files),'Only result JSON files')
    opening={str(p):pin(p) for p in files};docs={p.name:read(p) for p in files};require(len(docs)==len(files),'Distinct result basenames')
    plan=read(T/'experiment-plan-v02.json');data_path=Path(plan['data_export']['path']);require(pin(data_path)=={k:plan['data_export'][k] for k in ('bytes','sha256')},'Frozen source export pin');data=read(data_path)
    source_inputs={str(T/'experiment-plan-v02.json'):pin(T/'experiment-plan-v02.json'),str(data_path):pin(data_path)}
    for path,expected in plan['artifacts'].items():require(pin(Path(path))==expected,'Frozen recipe artifact drift')
    source_inputs.update(plan['artifacts'])
    spanpath=Path(plan['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula']['path'])
    continuation=Path(plan['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_continuation']['path'])
    implementation={name:plan['source_owner_pins'][module]['sha256'] for name,module in [('span','ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula'),('codec','ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_codec'),('canonical','ipfs_datasets_py.logic.legal_ir.canonical_contracts'),('grammar','ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder')]}
    summary=docs['summary.json'];false_flags(summary)
    require(summary['schema']=='temporal-contrast-source-only-two-arm-results/v1' and summary['status']=='completed' and summary['actual_new_updates']==64 and summary['equal_step_count']==32 and summary['actual_encoder_calls']==0 and summary['trained_dimensions']==[384] and summary['latent_enabled'] is False,'Complete bounded summary')
    require(summary['fresh_Adam_per_arm'] is True and summary['inherited_optimizer_moments'] is False and summary['same_parent_model'] is True and summary['same_batch_schedule'] is False,'Comparison scope')
    require(summary['semantic_accuracy'] is None and all(summary[k] is False for k in ('legal_fidelity_qualified','independent_semantic_holdout','checkpoint_selection_executed','default_promotion','Lake_executed')),'Scientific limits')
    require([a['name'] for a in summary['arms']]==['control','contrast'],'Two arm order')
    require(summary['opening_imported_owners']==summary['closing_imported_owners'] and set(summary['opening_imported_owners'])<=set(plan['source_owner_pins']),'Recorded producer closure')
    expected_names={'summary.json','baseline.json','all-data-schedules-before-models.json'}
    checkpoints={};checkpoint_contracts={};initial_outer={}
    init_spec=ast.literal_eval(next(n.value for n in ast.parse(continuation.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_INITIALIZATION' for t in n.targets)))
    for arm,recipe in zip(summary['arms'],plan['arms'],strict=True):
        name=arm['name'];cp=docs[name+'-checkpoint.json'];base=cp['base_checkpoint'];parent=cp['source_parent_checkpoint'];report=docs[name+'-training.json'];false_flags(cp,BASE_FALSE);false_flags(report,BASE_FALSE)
        require(set(cp)=={'schema','lineage_id','initialization','implementation','source_parent_checkpoint','source_parent_checkpoint_sha256','source_parent_optimizer_steps','initial_model_state_sha256','initial_base_checkpoint_sha256','context_contract','context_contract_sha256','base_checkpoint','parent_checkpoint_sha256',*BASE_FALSE},'Closed continuation serialization')
        require(cp['schema']=='warm-start-span-legal-formula-checkpoint/v1' and cp['lineage_id']=='warm_start_source_span_formula_v1' and cp['initialization']==init_spec,'Actual outer weight lineage')
        require(cp['implementation']=={'continuation_sha256':pin(continuation)['sha256'],'base_span':implementation},'Checkpoint source hash closure')
        shapes=serialized_base(base,implementation);serialized_base(parent,implementation)
        require(wire(cp)==(R/(name+'-checkpoint.json')).read_bytes(),'Canonical checkpoint serialization')
        require(digest(parent)==cp['source_parent_checkpoint_sha256']==plan['parent_base_canonical_sha256'] and digest(parent['model_state'])==cp['initial_model_state_sha256']==plan['parent_model_state_sha256'],'Embedded saved parent identity fd7/54e')
        require(cp['source_parent_optimizer_steps']==400 and parent['progress']==dict(epochs_completed=4,row_cursor=192,optimizer_steps=400),'Historical400 parent boundary')
        require(base['config']==parent['config'] and cp['context_contract']==plan['context_contract'] and cp['context_contract_sha256']==digest(cp['context_contract']),'Context and exact architecture config')
        initial=deepcopy(base);initial.update(model_state=deepcopy(parent['model_state']),optimizer_state=dict(schema='adam-default-betas-eps/v1',parameters={}),progress=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0),parent_checkpoint_sha256=None)
        require(digest(initial)==cp['initial_base_checkpoint_sha256']==base['parent_checkpoint_sha256'],'Fresh Adam zero-update base boundary')
        zero=deepcopy(cp);zero.update(base_checkpoint=initial,parent_checkpoint_sha256=None)
        require(digest(zero)==cp['parent_checkpoint_sha256']==report['previous_continuation_checkpoint_sha256'],'Fresh outer zero-update boundary')
        require(base['training_count']==recipe['training_count']==len(data['populations'][recipe['training_population']]) and base['training_manifest_sha256']==recipe['training_manifest_sha256']==digest(data['populations'][recipe['training_population']]),'Training manifest identity')
        require(base['tuning_count']==96 and base['tuning_manifest_sha256']==plan['tuning_manifest_sha256']==digest(data['populations']['old_tune']),'Tuning identity')
        planned=schedule(data['populations'][recipe['training_population']]);require(arm['planned_data_schedule']==planned and base['progress']==planned['final_progress'],'Deterministic schedule/final progress')
        require(report['checkpoint_sha256']==digest(cp) and report['base_checkpoint_sha256']==digest(base) and report['source_parent_checkpoint_sha256']==digest(parent) and report['context_contract_sha256']==cp['context_contract_sha256'],'Training checkpoint hash joins')
        require(report['optimizer_steps']==report['continuation_optimizer_steps_total']==arm['actual_new_updates']==32 and report['stopped_reason']=='step_limit' and report['training_executed'] is True and len(report['batch_losses'])==32,'Saved32 update report')
        changed=[k for k in base['model_state'] if base['model_state'][k]!=parent['model_state'][k]];require(set(changed)==set(report['changed_parameter_names']) and len(changed)==19 and all(not k.startswith('latent_') for k in changed),'Dormant latent tensors unchanged;19 source tensors changed')
        require(report['tuning']['rows_evaluated']==96 and report['tuning']['used_for_fit_or_selection'] is False and report['tuning']['complete'] is True,'Tuning diagnostics not selection')
        checkpoints[name]=cp;initial_outer[name]=zero;checkpoint_contracts[name]=dict(raw_pin=opening[str(R/(name+'-checkpoint.json'))],canonical_sha256=digest(cp),base_sha256=digest(base),source_parent_sha256=digest(parent),copied_initial_model_sha256=digest(parent['model_state']),initial_base_sha256=digest(initial),initial_outer_sha256=digest(zero),progress=base['progress'],model_tensors=len(shapes),adam_parameters=len(base['optimizer_state']['parameters']),adam_steps=32,changed_source_parameters=sorted(changed),dormant_latent_parameters_unchanged=True)
        for key in ('checkpoint','training','parity'):
            p=Path(arm[key]['path']);require(p.parent==R and opening[str(p)]=={k:arm[key][k] for k in ('bytes','sha256')},'Arm saved file pin')
        expected_names.update({name+'-checkpoint.json',name+'-training.json'})
    require(checkpoints['control']['source_parent_checkpoint']==checkpoints['contrast']['source_parent_checkpoint'],'Same embedded parent bytes')
    baseline=docs['baseline.json'];false_flags(baseline);require(baseline['fit_updates']==0 and baseline['original_parent_model_state_sha256']==plan['parent_model_state_sha256'] and baseline['checkpoint_sha256']==digest(initial_outer['control']),'Zero-update baseline')
    schedules=docs['all-data-schedules-before-models.json'];false_flags(schedules);require(schedules['model_imported'] is False and schedules['same_update_budget'] is True and schedules['same_batch_schedule'] is False and schedules['parent_model_state_sha256']==plan['parent_model_state_sha256'],'Pure schedule preparation')
    require(schedules['arms']==[dict(name=a['name'],training_count=a['training_count'],schedule=schedule(data['populations'][a['training_population']])) for a in plan['arms']],'Complete pre-model schedules')
    source_namespace={'hashlib':hashlib,'json':json,'math':math,'struct':struct,'SPAN_FIELDS':FIELDS,'OPTIONAL_FIELDS':FIELDS[2:],'MODALITIES':('O','P','F')}
    capture_path=Path(plan['source_owner_pins']['ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture']['path'])
    greedy=detached_functions(capture_path,{'_require','_wire','_same','_f32','_pair_winners','_verify_greedy'},source_namespace)
    jointpath=Path(plan['source_owner_pins']['ipfs_datasets_py.logic.legal_ir.joint_span_selection']['path'])
    joint_constants={'SCORE_SCHEMA':'joint-source-span-scores/v1','SCHEMA':'joint-copied-span-selection/v1','ORIGIN':'bounded_joint_source_span_selector','FIELDS':FIELDS,'OPTIONAL_FIELDS':FIELDS[2:],'QUALIFIERS':FIELDS[3:],'MODALITIES':('O','P','F'),'AMBIGUITY_GUARD':1e-7,'MAX_TOP_K':16,'MAX_SEARCH_NODES':50000,'FALSE':dict(qualified=False,admitted=False,formalized=False,roundtrip_ok=False,proof_authority=False,semantic_correctness_verified=False,promotion_performed=False,publication_performed=False,default_promoted=False,target_access=False,teacher_forcing=False,training_executed=False,model_execution_performed=False,encoder_execution_performed=False,Lake_executed=False)}
    joint_ns={'hashlib':hashlib,'json':json,'math':math,'struct':struct,**joint_constants,'_owner':lambda:SimpleNamespace(tokenize_source=tokenization,codec_module=SimpleNamespace(_rule=strict_rule))}
    joint=detached_functions(jointpath,{'JointSelectionError','_require','_raw','_f32','_keys','_validated','_choice','_rank_spans','_span','_canonical','_greedy','select_joint_spans'},joint_ns)
    runnerpath=Path(plan['runner_path']);score_ns={'require':require,'canonical':wire,'digest':digest,'closed':lambda v,k,l:require(type(v) is dict and set(v)==set(k),'Closed '+l),'f32':f32,'re':re,'hashlib':hashlib,'FIELDS':FIELDS,'FALSE':FALSE,'itertools':__import__('itertools')}
    scorer=detached_functions(runnerpath,{'score_panel'},score_ns)
    tables=[];counts={'panel_source_rows':0,'authored_score_rows':0,'saved_logit_joint_replays':0,'greedy_predicate_checks':0,'parity_source_rows':0};old_regressions=[]
    for state in ('baseline','control','contrast'):
        panels=summary['baseline_panels'] if state=='baseline' else next(a['diagnostics'] for a in summary['arms'] if a['name']==state)
        cp=initial_outer['control'] if state=='baseline' else checkpoints[state]
        require(panels==baseline['panels'] if state=='baseline' else True,'Baseline panels join')
        require([p['name'] for p in panels]==['old_tune','fresh_tune','fresh_challenge','law'],'Complete four panels')
        for panel,recipe in zip(panels,plan['diagnostic_panels'],strict=True):
            name=panel['name'];rows=data['populations'][name];raw=docs[state+'-'+name+'-raw.json'];selected=docs[state+'-'+name+'-joint.json'];score=docs[state+'-'+name+'-score.json'] if name!='law' else None
            require(panel['row_count']==recipe['count']==len(rows) and panel['has_authored_reference'] is recipe['has_authored_reference'] and panel['provenance']==recipe['provenance'],'Panel manifest/provenance')
            for kind in ('raw','joint','score'):
                if kind=='score' and name=='law':require(panel[kind] is None,'Target-free law score absent');continue
                p=Path(panel[kind]['path']);require(p==R/(state+'-'+name+'-'+kind+'.json') and opening[str(p)]=={k:panel[kind][k] for k in ('bytes','sha256')},'Panel result pin join');expected_names.add(p.name)
            false_flags(raw);false_flags(selected)
            require(raw['actual_source_forwards']==len(rows) and raw['extra_capture_forwards']==0 and raw['target_access'] is False and raw['teacher_forcing'] is False and raw['model_weights_unchanged'] is True and raw['original_greedy_observations_verified'] is True and raw['ambient_CPU_RNG_preserved'] is True,'Saved target-free capture contract')
            inf=raw['inference'];false_flags(inf,BASE_FALSE);require(inf['checkpoint_sha256']==digest(cp) and inf['base_checkpoint_sha256']==digest(cp['base_checkpoint']) and inf['source_parent_checkpoint_sha256']==plan['parent_base_canonical_sha256'] and inf['context_contract_sha256']==digest(plan['context_contract']) and inf['latent_ablation']=='none' and inf['target_access'] is False and inf['teacher_forcing'] is False and inf['training_executed'] is False,'Inference checkpoint/context joins')
            require(len(raw['occurrences'])==len(inf['rows'])==len(selected['rows'])==len(rows),'Full occurrence coverage')
            for incoming,capture,actual,jrow in zip(rows,raw['occurrences'],inf['rows'],selected['rows'],strict=True):
                source=incoming['source_text'];sourcehash=hashlib.sha256(source.encode()).hexdigest();require(incoming['id']==capture['id']==jrow['id'] and capture['source_sha256']==actual['source_sha256']==jrow['result']['source_sha256']==sourcehash,'Source/occurrence hash join')
                require(actual['latent_sha256']==digest(incoming['latent']) and actual['latent_input_enabled'] is False,'Dormant384 latent identity')
                require(capture['scores']['tokens']==tokenization(source),'Exact Unicode source tokens')
                greedy['_verify_greedy'](source,capture['scores'],actual);counts['greedy_predicate_checks']+=1
                replay=joint['select_joint_spans'](source,capture['scores'],top_k=8,max_search_nodes=50000);require(replay==jrow['result'],'Complete saved-logit selection replay');counts['saved_logit_joint_replays']+=1
                if actual['canonical_ir'] is not None:strict_rule(actual['canonical_ir'])
                false_flags(actual,BASE_FALSE);require(actual['target_access'] is False and actual['teacher_forcing'] is False and actual['training_executed'] is False,'Raw row no training/target')
            require(inf['decoded_count']==sum(r['status']=='decoded' for r in inf['rows']),'Raw decoded count')
            counts['panel_source_rows']+=len(rows)
            if score is not None:
                recomputed=scorer['score_panel'](rows,data['metadata'][name],raw,selected['rows']);require(recomputed==score,'Complete post-inference score reconstruction');counts['authored_score_rows']+=len(rows)
                tables.append(dict(state=state,panel=name,rows=len(rows),raw_exact=score['raw_exact_ir'],joint_exact=score['joint_exact_ir'],raw_abstentions=score['raw_abstentions'],temporal_presence_correct=score['temporal_presence_correct'],temporal_false_positives=score['temporal_false_positives'],temporal_false_negatives=score['temporal_false_negatives'],modality_exact=score['modality_exact'],joint_modality_exact=score['joint_modality_exact'],role_exact=score['role_exact_counts'],joint_role_exact=score['joint_role_exact_counts'],classes=score['classes'],pairs=len(score['pairwise_consistency']),pair_both_raw_exact=sum(p['raw_both_exact'] for p in score['pairwise_consistency']),pair_both_joint_exact=sum(p['joint_both_exact'] for p in score['pairwise_consistency']),pair_both_temporal_correct=sum(p['temporal_both_correct'] for p in score['pairwise_consistency'])))
                if state=='contrast' and name=='old_tune':
                    for row,actual,jrow,scored in zip(rows,inf['rows'],selected['rows'],score['rows'],strict=True):
                        if not scored['joint_exact_ir']:old_regressions.append(dict(id=row['id'],raw_exact=scored['raw_exact_ir'],joint_exact=scored['joint_exact_ir'],modality_exact=scored['joint_modality_exact'],mismatched_roles=[f for f in FIELDS if not scored['joint_role_exact'][f]],reference=row['canonical_ir'],raw=actual['canonical_ir'],joint=jrow['result']['canonical_ir']))
            else:
                require(all(set(row)=={'id','source_text','latent'} for row in rows),'Law contains no target/teacher labels')
                require(not (R/(state+'-law-score.json')).exists(),'No unreviewed-law exact score')
                tables.append(dict(state=state,panel='law',rows=8,raw_decoded=sum(r['status']=='decoded' for r in inf['rows']),joint_selected=sum(r['result']['status']=='selected' for r in selected['rows']),raw_exact=None,joint_exact=None,reference_scope='previously_exposed_unreviewed_target_free_law_only'))
        parity=docs[state+'-parity.json'];false_flags(parity);require(parity['passed'] is True and parity['source_count']==2 and parity['score_and_greedy_decisions_bit_equal'] is True and parity['genuine_latent_semantics_tested'] is False and parity['actual_encoder_calls']==0,'Dormant placeholder parity scope')
        require([x['name'] for x in parity['controls']]==['zeros','alternate_placeholders','disabled','rotated_placeholders'],'All four controls');projection=None
        for ctl in parity['controls']:
            p=Path(ctl['report']['path']);require(p.parent==R and opening[str(p)]=={k:ctl['report'][k] for k in ('bytes','sha256')},'Parity pin');expected_names.add(p.name);cap=docs[p.name];require(len(cap['occurrences'])==len(cap['inference']['rows'])==2,'Full parity rows')
            false_flags(cap);false_flags(cap['inference'],BASE_FALSE)
            require(cap['target_access'] is False and cap['teacher_forcing'] is False and cap['extra_capture_forwards']==0 and cap['actual_source_forwards']==2 and cap['model_weights_unchanged'] is True and cap['ambient_CPU_RNG_preserved'] is True,'Target-free same-forward parity capture')
            require(cap['inference']['latent_ablation']==ctl['control'] and cap['inference']['base_checkpoint_sha256']==digest(cp['base_checkpoint']) and cap['inference']['context_contract_sha256']==digest(plan['context_contract']),'Parity base/control contract')
            current=[dict(scores=c['scores'],raw={key:a.get(key) for key in ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')}) for c,a in zip(cap['occurrences'],cap['inference']['rows'],strict=True)]
            require(projection is None or current==projection,'Bit-equal saved controls');projection=current;require(cap['inference']['checkpoint_sha256']==digest(cp),'Parity same saved state')
            for index,(row,capture,actual) in enumerate(zip(data['populations']['fresh_tune'][:2],cap['occurrences'],cap['inference']['rows'],strict=True)):
                sourcehash=hashlib.sha256(row['source_text'].encode()).hexdigest()
                vector=row['latent'] if ctl['name']=='zeros' else ([.25 if index==0 else -.25]*384)
                if ctl['name']=='rotated_placeholders':vector=[-.25 if index==0 else .25]*384
                require(row['id']==capture['id'] and capture['source_sha256']==actual['source_sha256']==sourcehash and actual['latent_sha256']==digest(vector) and actual['latent_input_enabled'] is False,'Parity source/latent hash scope')
                joint['_validated'](row['source_text'],capture['scores']);greedy['_verify_greedy'](row['source_text'],capture['scores'],actual);counts['greedy_predicate_checks']+=1;counts['parity_source_rows']+=1
        pp=summary['baseline_parity'] if state=='baseline' else next(a['parity'] for a in summary['arms'] if a['name']==state);require(pp['path']==str(R/(state+'-parity.json')) and {k:pp[k] for k in ('bytes','sha256')}==opening[pp['path']],'Parity summary join');expected_names.add(state+'-parity.json')
    require(set(docs)==expected_names and len(docs)==55,'Closed complete55 result files')
    require(counts==dict(panel_source_rows=528,authored_score_rows=504,saved_logit_joint_replays=528,greedy_predicate_checks=552,parity_source_rows=24),'Complete validation counts')
    require(len(old_regressions)==4,'Honest four old regressions')
    for path,expected in opening.items():require(pin(Path(path))==expected,'Closing result artifact drift')
    require({str(p):pin(p) for p in R.rglob('*') if p.is_file()}==opening,'Closing complete result map')
    limitations=['One seed1729; unequal108/168 training populations and different batch schedules. Equal32 new updates per arm support a bounded engineering comparison, not causal attribution to a single curriculum factor.',
        'The96/36/36 references are caller-authored engineering targets. The8 law sources were already exposed and carry no independently reviewed targets; no legal semantic accuracy is measured.',
        '384D is configured with latent conditioning disabled. Placeholder controls do not qualify genuine8D/384D/768D autoencoder semantics or a cross-dimension decoder comparison.',
        'Pure Python parsed only the two new checkpointJSONs and their embedded provenance, without model construction/restoration/forward. The original parent file and13 historical4GB modelstates remained opaque; original parent raw5df identity is source-pinned.',
        'Complete saved-logit joint replay compiles named pure frozen-source predicates with structural source/canonical-rule stubs. This authenticates saved selection/search arithmetic and copied IR, not a new compiler run, full family qualification or independent semantic validation.',
        'Saved Adam steps, finite tensors, schedule progress, changed weights and training reports are mutually consistent; this audit does not independently trace runtime gradient/optimizer execution or prove objective-loss values by numerical replay.',
        'Resource/runtime closure is reviewed separately. No Lake build, broader logic-family compliance, USCode gold fidelity, new default promotion, model-state adoption, Git/HF publication or checkpoint selection is granted.']
    analysis=dict(schema='temporal-contrast-saved-result-analysis/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),result_root=str(R),result_file_count=55,result_bytes=sum(x['bytes'] for x in opening.values()),source_artifact_pins=source_inputs,source_export_pin=pin(data_path),validation_counts=counts,checkpoint_contracts=checkpoint_contracts,panels=tables,old_regressions=old_regressions,limits=limitations,reviewer_actions=dict(numerical_imports=0,model_restores=0,model_forwards=0,optimizer_updates=0,original_parent_JSON_parses=0,historical4GB_modelstate_parses=0,new_checkpoint_JSONs_parsed=2,resource_API_calls=0,leases_or_locks=0,compiler_or_network_calls=0,Git_HF_mutations=0))
    review=dict(schema='temporal-contrast-result-independent-review/v1',passed=True,findings=[],result_root=str(R),artifacts=opening,scope='Independent stdlib-only saved-result audit: closed55 resultJSON pins, source/occurrence/token/score/hash joins, full528 saved-logit joint replays and552 greedy predicate checks,504 authored score reconstructions, two finite canonical serialized new checkpoints with parent/freshAdam/progress joins, and all disabled384 placeholder controls. No model restore/forward or runtime operation.',limitations=limitations)
    require(set(review)=={'schema','passed','findings','result_root','artifacts','scope','limitations'} and all(set(v)=={'bytes','sha256'} for v in review['artifacts'].values()),'Exact requested closed review schema')
    for path,value in ((ANALYSIS,analysis),(REVIEW,review)):
        with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        path.chmod(0o444)
    print(json.dumps(dict(passed=True,review=pin(REVIEW),analysis=pin(ANALYSIS),result_files=55,validation_counts=counts,panel_exact=[{k:v for k,v in t.items() if k in ('state','panel','rows','raw_exact','joint_exact','raw_abstentions')} for t in tables]),sort_keys=True))


if __name__=='__main__':main()

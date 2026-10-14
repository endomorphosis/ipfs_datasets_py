#!/usr/bin/env python3
"""Unqualified source: independent stdlib F15 recount; actual main is gated.

Only seven pinned F14 pure AST helpers are reused. No analyzer, production,
numerical or model import occurs. Reported gradient/moment evidence is checked
structurally; absent logits and live tensors are never numerically replayed.
"""
from pathlib import Path
import ast
import builtins
import copy
import hashlib
import json
import math
import os
import re
import random
import stat
import struct
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
HELPER = ROOT.parent/'legal-balanced-execution-20261014-01/review_conditions_balanced_result_recount_v01.py'
HELPER_PIN = dict(path=str(HELPER), bytes=46595, sha256='0c5b68645cc66e7758d1750c878f5be9fb117faad841fe27f73391c8ccbce8bf')
CONTRACT = ROOT/'evaluation-contract-v01.json'
CONTRACT_PIN = dict(path=str(CONTRACT), bytes=12913, sha256='a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e')
MODULE_ROOT=ROOT/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer'
TRAINER=MODULE_ROOT/'legal_span_actor_refinement.py'
TARGETED=MODULE_ROOT/'legal_span_targeted_loss.py'
SPLIT=MODULE_ROOT/'legal_span_split_features.py'
TRAINING_SOURCE_PINS=(
    dict(path=str(TRAINER),bytes=56952,sha256='a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'),
    dict(path=str(TARGETED),bytes=49658,sha256='f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b'),
    dict(path=str(SPLIT),bytes=52067,sha256='886a0cde9924dceb5f5a4b655a995eb60a8f3fb954408d991fe4b4eb23ade0cd'))
QUALIFICATION = ROOT/'result-recount-source-independent-review-v01.json'
INPUTS = ROOT/'result-recount-inputs-v01.json'
OUTPUT = ROOT/'actor-refinement-independent-recount-v01.json'
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law', 'fresh_dev', 'fresh_test')
COUNTS = dict(zip(PANELS, (96,36,36,72,72,72,8,36,36)), training168=168)
SCOPES = tuple(panel for panel in (*PANELS,'training168') if panel != 'law')
STATES = ('parent','initial','trained')
HELPERS = ('coordinates','bits','choice','actor_coverage','coverage_summary','paired_score','presence_recount')
OBSERVED = {}
FREEZE_PASSED = False
TRAINING_TRACE_RECOUNT_CONFIGURED = True
sys.dont_write_bytecode = True


def require(value, message):
    if not value: raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def f32(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite typed binary32 scalar required')
    return struct.unpack('!f',struct.pack('!f',value))[0]


def ranked(scores, role):
    n=len(scores['tokens'])
    require(1<=n<=128 and len(scores['start_logits'][role])==len(scores['end_logits'][role])==n,'Complete bounded pointer vectors required')
    return sorted(((f32(scores['start_logits'][role][a]+scores['end_logits'][role][b]),a,b)
        for a in range(n) for b in range(a,n)),key=lambda item:(-item[0],item[1],item[2]))


def denied_import(name, *args, **kwargs):
    raise ValueError('Detached recount helper import denied: '+name)


def load_helpers():
    identity(HELPER,HELPER_PIN)
    tree=ast.parse(HELPER.read_bytes())
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in HELPERS]
    require({node.name for node in nodes}==set(HELPERS) and len(nodes)==len(HELPERS),'Exact seven immutable helper definitions required')
    require(not any(node.decorator_list or any(isinstance(child,(ast.Import,ast.ImportFrom)) for child in ast.walk(node)) for node in nodes),'No decorated/importing helper allowed')
    namespace=dict(FIELDS=FIELDS,require=require,digest=digest,f32=f32,ranked=ranked,math=math,re=re,struct=struct)
    namespace['__builtins__']=dict(vars(builtins),__import__=denied_import)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(HELPER)+'#seven-pure-helpers','exec'),namespace)
    identity(HELPER,HELPER_PIN)
    return {name:namespace[name] for name in HELPERS}


def detached_definitions(path,names,namespace):
    nodes=[n for n in ast.parse(Path(path).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    require(len(nodes)==len(names) and {n.name for n in nodes}==set(names),'Exact detached training validator definitions required')
    require(not any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in nodes),'No detached decorators/imports')
    namespace['__builtins__']=dict(vars(builtins),__import__=denied_import)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#pure-training-validators','exec'),namespace)
    return namespace


def load_training_validators():
    for pin in TRAINING_SOURCE_PINS:identity(pin['path'],pin)
    constants={};wanted={'ORIGINAL_PARAMETER_NAMES','FEATURE_PARAMETER_NAMES','SPLIT_FEATURE_PARAMETER_NAMES','MODEL_PARAMETER_NAMES'}
    for node in ast.parse(SPLIT.read_bytes()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in wanted for t in node.targets):
            constants['__builtins__']=dict(vars(builtins),__import__=denied_import)
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(SPLIT)+'#parameter-name-constants','exec'),constants)
    require(wanted<=set(constants) and len(constants['MODEL_PARAMETER_NAMES'])==34,'Exact original34 ordered names required')
    head=('actor_start.weight','actor_start.bias','actor_end.weight','actor_end.bias');vectors=('actor_attention.query','actor_context.gate')
    model=constants['MODEL_PARAMETER_NAMES']+head+vectors+('conditions_presence.weight','conditions_presence.bias')
    span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z'))
    raw=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    target=dict(_require=require,_raw=raw,checkpoint_digest=digest,copy=copy,math=math,random=random,struct=struct,span=span,
        SPAN_FIELDS=FIELDS,POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',MAX_SOURCE_TOKENS=128,MAX_NEW_STEPS=32,MAX_SECONDS=32,
        LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995')
    target_names=('_policy','_validate_policy','_progress','_batch_indices','_advance_progress','_batch_trace_entry','_trace_summary','_span_coordinates','_actor_domain','_f32','_validate_objective_diagnostics')
    detached_definitions(TARGETED,target_names,target)
    trainer=dict(_require=require,_raw=raw,checkpoint_digest=digest,math=math,span=span,targeted=SimpleNamespace(**{n:target[n] for n in target_names}),
        HEAD_PARAMETER_NAMES=head,FEATURE_PARAMETER_NAMES=vectors,TRAINABLE_PARAMETER_NAMES=head+vectors,MODEL_PARAMETER_NAMES=model,
        BASE_PARAMETER_NAMES=tuple(n for n in model if n not in head+vectors),INACTIVE_ROWS=(1,2,3,4,5),OBJECTIVES=('actor-refinement-ce',),
        POLICY_SCHEMA='bounded-actor-refinement-adapter-policy/v1')
    detached_definitions(TRAINER,('_partition','_policy','_validate_policy','_validate_objective_entry','_validate_freeze_entry','_validate_feature_entry'),trainer)
    for pin in TRAINING_SOURCE_PINS:identity(pin['path'],pin)
    return dict(trainer=trainer,targeted=target)


def projection(scores, full=True):
    """Full initial bits; final excludes ONLY the two actor pointer vectors."""
    require(type(full) is bool and set(scores['presence_logits'])==set(FIELDS[2:])
        and set(scores['start_logits'])==set(scores['end_logits'])==set(FIELDS)
        and len(scores['modality_logits'])==3,'Exact modality/four-presence/six-pointer geometry required')
    n=len(scores['tokens']);require(1<=n<=128,'Bounded token geometry required')
    require(all(len(value)==2 for value in scores['presence_logits'].values())
        and all(len(value)==n for side in ('start_logits','end_logits') for value in scores[side].values()),'Complete score vector geometry required')
    return dict(modality_logits=scores['modality_logits'],presence_logits=dict(scores['presence_logits']),
        **{side:{role:value for role,value in scores[side].items() if full or role!='actor'} for side in ('start_logits','end_logits')})


def initial_prediction_parity(before_raw,after_raw,before_joint,after_joint):
    keys=('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')
    require(len(before_raw)==len(after_raw)==len(before_joint)==len(after_joint),'Complete initial prediction parity scope required')
    for a,b,left,right in zip(before_raw,after_raw,before_joint,after_joint,strict=True):
        require({key:a.get(key) for key in keys}=={key:b.get(key) for key in keys},'Initial complete saved greedy predictions differ')
        require(left==right,'Initial complete saved joint envelope differs')


def independent_acceptance(contract, records, permissions, technical_passed=True):
    require(type(technical_passed) is bool and tuple(contract['states'])==STATES
        and tuple(contract['paired_scored_scopes'])==SCOPES,'Exact three-state/nine-scope criterion required')
    criterion=contract['strict_scientific_success']
    require(criterion['training168']['minimum_accepted_raw_and_joint']==155
        and criterion['training168']['raw_full_IR_strictly_greater_than']==154
        and criterion['training168']['joint_full_IR_strictly_greater_than']==154
        and criterion['no_complete_IR_loss_IDs_vs_N11']['allowed_loss_count_each_scope_and_view']==0
        and tuple(criterion['no_complete_IR_loss_IDs_vs_N11']['scopes'])==SCOPES
        and criterion['no_complete_IR_loss_IDs_vs_N11']['views']==['raw','joint']
        and criterion['permission_retention']['gold_permission_count']==32
        and criterion['permission_retention']['allowed_losses']==criterion['permission_retention']['allowed_abstentions']==0,
        'Fixed preregistered155/zero-loss/all32-permission criterion required')
    require(set(records)=={(state,panel) for state in STATES for panel in SCOPES},'Complete27 authored score scopes required')
    require(all(len(records[state,panel])==len({row['id'] for row in records[state,panel]})==COUNTS[panel]
        and all(type(row[route]['full_IR']) is bool for row in records[state,panel] for route in ('raw','joint'))
        for state in STATES for panel in SCOPES),'Complete unique typed score rows required')
    loss_ids={}
    for panel in SCOPES:
        before,after=records['parent',panel],records['trained',panel]
        require([r['id'] for r in before]==[r['id'] for r in after] and len(before)==COUNTS[panel]
            and len({r['id'] for r in before})==len(before),'Complete ordered unique paired IDs required')
        loss_ids[panel]={route:[a['id'] for a,b in zip(before,after,strict=True)
            if a[route]['full_IR'] and not b[route]['full_IR']] for route in ('raw','joint')}
    train={route+'_full_IR':sum(row[route]['full_IR'] for row in records['trained','training168']) for route in ('raw','joint')}
    train.update(minimum_required=155,passed=all(value>=155 for value in train.values()))
    no_loss=dict(views=['raw','joint'],scopes=list(SCOPES),loss_ids_by_scope=loss_ids,
        passed=not any(ids for value in loss_ids.values() for ids in value.values()))
    require(set(permissions)==set(STATES),'All three permission states required')
    permission_pass=all(p['count']==len(p['ids'])==len(set(p['ids']))==32
        and p['raw_P_to_P']==p['joint_P_to_P']==32 and p['losses']==p['abstentions']==0 for p in permissions.values())
    retained=dict(count=32,passed=permission_pass)
    return dict(schema='actor-refinement-scientific-acceptance/v1',technical_gate_passed=technical_passed,
        training168=train,no_complete_IR_loss_IDs_vs_N11=no_loss,all32_permission_retention=retained,
        scientific_success=technical_passed and train['passed'] and no_loss['passed'] and permission_pass)


def identity(path, expected=None):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.is_file() and not path.is_symlink(),'Physical ordinary evidence required')
    require(not {'private-runtime-snapshots','resource-snapshots'}&set(path.parts)
        and path.name not in {'resources-start.json','resources-final.json','disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json'},'Private/global evidence denied')
    before=path.stat();require(0<before.st_size<=32*1024*1024,'Bounded saved evidence required')
    data=path.read_bytes();after=path.stat();stable=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(stable(before)==stable(after) and len(data)==before.st_size,'Evidence changed during read')
    pin=dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    if expected:require(all(pin[k]==expected[k] for k in ('bytes','sha256')) and ('path' not in expected or pin['path']==expected['path']),'Evidence descriptor differs')
    require(str(path) not in OBSERVED or OBSERVED[str(path)]==pin,'Consumed evidence changed');OBSERVED[str(path)]=pin
    return pin


def read(value):
    path=Path(value['path']) if type(value) is dict else Path(value)
    require('checkpoint' not in path.name.lower(),'Checkpoint JSON parse denied')
    require(FREEZE_PASSED or path in {QUALIFICATION,INPUTS,CONTRACT,ROOT/'actor-refinement-output-freeze-v01.json',ROOT/'actor-refinement-ce-runtime-review-v01.json'},'No results/references before qualified complete freeze')
    pin=identity(path,value if type(value) is dict else None);raw=path.read_bytes()
    require(len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'Consumed bytes differ')
    def pairs(items):
        result={}
        for key,item in items:require(key not in result,'Duplicate JSON refused');result[key]=item
        return result
    def finite(value):
        result=float(value);require(math.isfinite(result),'Nonfinite JSON refused');return result
    result=json.loads(raw,object_pairs_hook=pairs,parse_float=finite,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON refused')))
    identity(path,pin);return result


def audit(event,args):
    if event=='import' and args[0].split('.')[0] not in sys.stdlib_module_names:raise ValueError('Only stdlib imports permitted')
    require(not event.startswith(('subprocess.','socket.','os.exec','os.spawn')) and event not in {'os.system','os.fork','fcntl.flock','os.mkdir','os.remove','os.rename','os.replace','os.unlink','os.kill','os.killpg'},'Process/network/resource/shared operation denied')
    if event=='open' and isinstance(args[0],(str,bytes)):
        target=Path(os.fsdecode(args[0])).absolute();mode,flags=args[1:3]
        require(not {'private-runtime-snapshots','resource-snapshots'}&set(target.parts)
            and target.name not in {'resources-start.json','resources-final.json','disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json'},'Private/global open denied')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or target==OUTPUT and isinstance(flags,int) and bool(flags&os.O_EXCL),'Only exclusive own receipt write permitted')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'Only own output freeze permitted')


def authenticate_freeze(freeze,runtime,schema):
    require(freeze['schema']==schema and runtime['passed'] is True and runtime['findings']==[]
        and freeze['all_outputs_frozen'] is freeze['authorizes_authored_eval_scoring'] is True
        and freeze['statutory_reference_scoring_authorized'] is False and freeze['actual_returned_optimizer_updates']==32
        and len(freeze['results'])==runtime['output_file_count']==62 and runtime['outputs']==freeze['results']
        and freeze['plan']==runtime['plan'],'Qualified complete62 freeze/runtime required')
    base=Path(freeze['summary']['path']).parent
    names={'data-schedule-before-models.json','cell-checkpoint.json','cell-training.json','summary.json','initial-parent-head-parity.json','trained-frozen-head-retention.json'}
    names.update(stage+'-'+panel+'-'+view+'.json' for stage in ('baseline','trained') for panel in PANELS for view in ('raw','joint'))
    names.update(label+'-'+view+'.json' for label in ('initial-training168','parent-training168','trained-training168','parent-fresh_dev','parent-fresh_test') for view in ('raw','joint'))
    for stage in ('initial','trained'):
        names.add(stage+'-parity.json');names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    require(len(names)==62 and set(freeze['results'])=={str(base/name) for name in names},'Exact flat62 output inventory required')
    for path,pin in freeze['results'].items():identity(path,pin);require(stat.S_IMODE(Path(path).stat().st_mode)==0o444,'Frozen output mode differs')
    require(freeze['summary']==dict(path=str(base/'summary.json'),**freeze['results'][str(base/'summary.json')]),'Frozen summary descriptor differs')


def frozen_descriptor(value, freeze):
    require(set(value)=={'path','bytes','sha256'} and value['path'] in freeze['results']
        and all(value[k]==freeze['results'][value['path']][k] for k in ('bytes','sha256')),'Consumed result outside exact qualified freeze')
    return value


def load_populations(plan,contract):
    old=ROOT.parent/'legal-temporal-adapter-20261013-01'
    freeze=read(dict(path=str(old/'two-cell-output-freeze-v01.json'),bytes=33740,sha256='a074501402f7c5f8e1dcbded4daa326989a5449507af1b1464ab5aef56978728'))
    custody=read(dict(path=str(old/'evaluation-contract-v01.json'),bytes=27955,sha256='07a55d285882cac62207fb7008bbca55746c86a56c7aa3cd4a96374fdd6bf87e'))
    pin=freeze['reference_source_export'];require(custody['raw_artifact_pins'][pin['path']]=={k:pin[k] for k in ('bytes','sha256')},'Old reference custody differs')
    full=read(pin);packet=read(freeze['reference_packet']);fresh=read(contract['fresh_reference_packet']);data=read(plan['data_export'])
    populations=dict(full['diagnostic_populations']);populations['authored_eval']=[row['model_example'] for row in packet['geometry_review_packet']['authored_eval']]
    for panel in ('fresh_dev','fresh_test'):populations[panel]=fresh['populations'][panel]
    populations['training168']=data['training_rows'];require(populations['training168']==full['training_populations']['mixed'],'Exact168 training references required')
    require(all('canonical_ir' not in row for row in populations['law']),'Law8 must remain unscored')
    require(all(len(populations[p])==COUNTS[p] for p in (*PANELS,'training168')),'All ten population counts required')
    rows=sum((populations[p] for p in (*PANELS,'training168')),[])
    require(len(rows)==len({r['id'] for r in rows})==len({r['source_text'] for r in rows})==632,'Distinct632 source scope required')
    references={pin['path'],freeze['reference_packet']['path'],contract['fresh_reference_packet']['path']}
    require(references<=set(plan['forbidden_reference_paths']) and not references&set(plan['artifacts']),'Evaluation references entered model plan')
    return populations


def permission_recount(sources,raw,chosen):
    ids=[];retained=dict(raw=0,joint=0);losses=set();abstained=set()
    for source,a,b in zip(sources,raw['inference']['rows'],chosen,strict=True):
        if source['canonical_ir']['rules'][0]['modality']!='P':continue
        identifier=source['id'];ids.append(identifier)
        for route,pred,success in (('raw',a,'decoded'),('joint',b['result'],'selected')):
            if pred['status']!=success:abstained.add(identifier)
            elif pred['canonical_ir']['rules'][0]['modality']=='P':retained[route]+=1
            else:losses.add(identifier)
    require(len(ids)==len(set(ids))==32,'Exactly32 source-gold permissions required')
    return dict(count=32,ids=ids,raw_P_to_P=retained['raw'],joint_P_to_P=retained['joint'],losses=len(losses),abstentions=len(abstained))


def recount_training(report, training, schedule):
    """Authenticate source-bound32 returned traces; no numerical gradient/CE replay."""
    validators=load_training_validators();owner=validators['trainer'];target=validators['targeted'];coordinates=load_helpers()['coordinates']
    require(len(training)==len({row['id'] for row in training})==168,'Exact unique168 authored training sources required')
    require(report['schema']=='bounded-actor-refinement-adapter-training/v1' and report['optimizer_steps']==report['continuation_optimizer_steps_total']==32
        and report['actor_training_count']==168 and report['training_executed'] is True and report['stopped_reason']=='step_limit'
        and report['tuning']==dict(rows_evaluated=0,used_for_fit_or_selection=False),'Exactly32 returned steps/zero tuning required')
    source='b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9'
    require(report['source_conditions_presence_checkpoint_sha256']=='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd'
        and report['source_conditions_presence_model_state_sha256']==report['initial_model_state_sha256']==report['training_call_initial_model_state_sha256']==source
        and report['source_conditions_presence_optimizer_steps']==32,'Trained N11 initial source identity differs')
    policy=owner['_validate_policy'](report['training_policy']);partition=owner['_partition']();names=owner['TRAINABLE_PARAMETER_NAMES']
    require(report['training_policy_sha256']==digest(policy) and report['parameter_partition']==partition
        and report['optimizer_parameter_order']==list(names) and report['stored_trainable_scalar_count']==908 and report['active_trainable_scalar_count']==258,
        'Exact42/36/6 ordered908/258/650 partition required')
    frozen=report['source_frozen36_state_sha256'];inactive=report['inactive_head_rows_sha256_initial']
    require(all(report[k]==frozen for k in ('frozen_parent36_sha256_initial','frozen_parent36_sha256_final','frozen_parameters_sha256_initial','frozen_parameters_sha256_final'))
        and report['inactive_head_rows_sha256_final']==inactive,'Actual source frozen36/inactive650 endpoint hashes differ')
    require(all(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) for value in (frozen,inactive,report['final_model_state_sha256'])),'Typed state hashes required')
    initial=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0);final=dict(epochs_completed=2,row_cursor=48,optimizer_steps=32)
    require(set(schedule)=={'batch_indices','batch_ids','batch_indices_sha256','final_progress'}
        and schedule['batch_indices_sha256']==digest(schedule['batch_indices']) and schedule['final_progress']==final,
        'Closed four-field prepared schedule digest/final progress required')
    batch_trace=report['batch_trace'];batches=batch_trace['batches']
    require(len(batches)==32 and batch_trace==target['_trace_summary'](batches,initial,final,policy['objective_policy'],training)
        and [b['indices'] for b in batches]==schedule['batch_indices'] and [b['ids'] for b in batches]==schedule['batch_ids']
        and report['batch_losses']==[b['loss'] for b in batches],'Exact1729 source-authenticated32x12 returned schedule required')
    traces={kind:report[kind+'_trace'] for kind in ('objective','freeze','feature')}
    for kind,trace in traces.items():
        require(trace['schema']=='completed-actor-refinement-adapter-'+kind+'-trace/v1'
            and trace['completed_updates']==len(trace['batches'])==32 and trace['batches_sha256']==digest(trace['batches'])
            and trace['independent_numerical_kernel_trace'] is False,'Exact completed32 trace schema/digest required')
    require(traces['objective']['evaluation_references_used'] is False,'Evaluation references prohibited in objective')
    prior=None;occurrences=0
    for step,(batch,objective,freeze,feature) in enumerate(zip(batches,*(traces[k]['batches'] for k in ('objective','freeze','feature')),strict=True),1):
        require(batch['optimizer_step']==step and len(batch['indices'])==len(batch['ids'])==12,'Every completed update must authenticate12 rows')
        owner['_validate_objective_entry'](objective,batch,policy);owner['_validate_freeze_entry'](freeze,batch);owner['_validate_feature_entry'](feature,batch)
        before,after=freeze['branch_digests_before'],freeze['branch_digests_after']
        require(freeze['source_frozen36_state_sha256']==freeze['frozen_before']==freeze['frozen_after']==frozen
            and freeze['inactive_before']==freeze['inactive_after']==inactive and (prior is None or prior==before),'Frozen/inactive source or branch continuity differs')
        if step==1:require(before==report['initial_branch_digests']==report['training_call_initial_branch_digests'],'Trained N11 initial branch chain differs')
        for label,branch in (('query','actor_attention_query_sha256'),('gate','actor_context_gate_sha256')):
            require(feature[label+'_before_sha256']==before[branch] and feature[label+'_after_sha256']==after[branch],'Feature vector digests must join actual frozen trace branches')
        for index,identifier,row,base in zip(batch['indices'],batch['ids'],objective['details']['rows'],objective['details']['base_objective']['rows'],strict=True):
            source_row=training[index];tokens,gold=coordinates(source_row);nonactor={role:list(value) for role,value in gold.items() if role!='actor'}
            require(source_row['id']==identifier==row['id'] and row['training_index']==index and row['actor_gold_coordinates']==list(gold['actor'])
                and row['token_count']==len(tokens) and base['source_sha256']==hashlib.sha256(source_row['source_text'].encode()).hexdigest()
                and base['present_gold_nonactor_coordinates']==nonactor,'Every one of384 source/gold actor and nonactor-domain joins required')
            occurrences+=1
        prior=after
    require(occurrences==384 and prior==report['final_branch_digests'],'Exact384 rows/final branch endpoint required')
    learning={name+'_changed_updates':sum(row[name+'_changed'] for row in traces['feature']['batches']) for name in ('query','gate')}
    learning.update({name+'_nonzero_gradient_updates':sum(not row[name+'_gradient_exact_zero'] for row in traces['feature']['batches']) for name in ('query','gate','context','residual')})
    require(report['feature_learning']==learning and report['gradient_norm_max']==max(b['gradient_norm_before_clip'] for b in batches)
        and type(report['changed_parameter_names']) is list and len(set(report['changed_parameter_names']))==len(report['changed_parameter_names'])
        and set(report['changed_parameter_names'])<=set(names),'Feature learning/gradient summary or changed parameter allowlist differs')
    forward=report['forward_accounting'];counter_names=('source_model_forwards','actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards')
    require(forward['schema']=='actor-refinement-adapter-training-forward-accounting/v1' and forward['actual_model_counter_deltas']==dict.fromkeys(counter_names,32)
        and all(forward[k]==32 for k in ('training_model_forward_calls','training_actor_features_model_calls','training_modality_encoder_calls','training_conditions_presence_head_calls'))
        and forward['training_span_encoder_calls']==64 and forward['training_source_row_occurrences']==384
        and forward['tuning_model_forward_calls']==forward['teacher_model_forward_calls']==0 and forward['feature_paths_per_source_model_forward']==3
        and forward['restore_validation_and_external_evaluation_forwards_included'] is False,'Actual32 calls/384 occurrences/zero teacher or tuning accounting differs')
    return dict(updates=32,source_occurrences=384,frozen36=True,inactive650=True,source_target_joins=True,objective='actor-refinement-ce',
        actor_ranking_enabled=False,presence_ce_weight=1,training_policy_sha256=digest(policy),batch_trace_sha256=digest(batches),
        **{kind+'_trace_sha256':traces[kind]['batches_sha256'] for kind in traces},feature_learning=learning,source_frozen36_state_sha256=frozen,
        independent_numerical_gradient_proof=False,scalar_CE_recomputed=False)


def main():
    global FREEZE_PASSED
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'Exclusive argument-free recount required')
    require(TRAINING_TRACE_RECOUNT_CONFIGURED is True,'F15 training trace hook must be source-bound before qualification')
    sys.addaudithook(audit);own=identity(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-refinement-result-recount-source-independent-review/v1' and qualification['passed'] is True
        and qualification['findings']==[] and qualification['observer']==own,'Exact qualified recounter required')
    for path,pin in qualification['artifacts'].items():identity(path,pin)
    require(all(qualification['artifacts'].get(pin['path']) in (pin,{k:pin[k] for k in ('bytes','sha256')}) for pin in (HELPER_PIN,CONTRACT_PIN,*TRAINING_SOURCE_PINS)),'Actual contract and immutable helper/trainer source closure must be qualified')
    helpers=load_helpers();inputs=read(INPUTS)
    require(set(inputs)=={'schema','passed','findings','freeze','analysis'} and inputs['schema']=='actor-refinement-result-recount-inputs/v1'
        and inputs['passed'] is True and inputs['findings']==[] and inputs['freeze']['path']==str(ROOT/'actor-refinement-output-freeze-v01.json')
        and inputs['analysis']['path']==str(ROOT/'actor-refinement-result-analysis-v01.json'),'Closed actual root inputs required')
    freeze=read(inputs['freeze']);runtime=read(freeze['runtime_review'])
    require(runtime['schema']=='actor-refinement-runtime-independent-review/v1','Exact qualified F15 runtime required')
    authenticate_freeze(freeze,runtime,'actor-refinement-output-freeze/v1');FREEZE_PASSED=True
    contract=read(CONTRACT_PIN);plan=read(freeze['plan']);summary=read(freeze['summary']);analysis=read(inputs['analysis'])
    require(contract['schema']=='actor-refinement-evaluation-contract/v1' and plan['evaluation_contract']==CONTRACT_PIN
        and plan['source_checkpoint']==contract['source_parent'] and plan['source_model_state_sha256']==contract['source_model_state_sha256'],'Exact trained N11 donor/contract required')
    require(analysis['schema']=='actor-refinement-exposed-result-analysis/v1' and analysis['passed'] is True and analysis['findings']==[]
        and analysis['freeze']==inputs['freeze'] and analysis['runtime_review']==freeze['runtime_review'] and analysis['plan']==freeze['plan']
        and (analysis['panel_count'],analysis['authored_score_sets'],analysis['paired_panel_count'])==(30,27,9),'Exact30/27/9 analysis joins required')
    populations=load_populations(plan,contract);parent=contract['completed_frozen_parent']
    pf=read(parent['freeze']);pr=read(parent['runtime_review']);authenticate_freeze(pf,pr,'conditions-presence-output-freeze/v1');review=read(parent['independent_review'])
    require(review['passed'] is True and review['findings']==[] and review['freeze']==parent['freeze'] and review['plan']==parent['plan']
        and parent['new_control_forwards']==parent['new_control_updates']==0,'Frozen sole N11 comparator custody required')
    ps=read(pf['summary']);require(ps['checkpoint']==plan['source_checkpoint'],'Exact completed N11 donor checkpoint required')
    captures={(state,p):summary['baseline_panels' if state=='initial' else 'diagnostics'][p] for state in ('initial','trained') for p in PANELS}
    for state in ('initial','trained'):captures[state,'training168']=summary['initial_training_capture' if state=='initial' else 'final_training_capture']
    for p in PANELS:captures['parent',p]=ps['diagnostics'][p]
    captures['parent','training168']=ps['final_training_capture']
    loaded={};panels=[];records={};coverage={};newinference=0
    for (state,panel),pair in captures.items():
        sources=populations[panel];custody=pf if state=='parent' else freeze
        raw=read(frozen_descriptor(pair['raw'],custody));chosen=read(frozen_descriptor(pair['joint'],custody))['rows'];loaded[state,panel]=(raw,chosen)
        require(len(sources)==len(raw['occurrences'])==len(raw['inference']['rows'])==len(chosen),'Complete source capture scope required')
        if state!='parent':newinference+=len(sources)
        flags=[];cov=[]
        for source,occ,greedy,joint in zip(sources,raw['occurrences'],raw['inference']['rows'],chosen,strict=True):
            sha=hashlib.sha256(source['source_text'].encode()).hexdigest()
            require(source['id']==occ['id']==joint['id'] and occ['source_sha256']==greedy['source_sha256']==sha,'Ordered source ID/SHA join required')
            tokens=[dict(text=m.group(),start=m.start(),end=m.end()) for m in re.finditer(r'\w+|[^\w\s]',source['source_text'])]
            require(tokens==occ['scores']['tokens'],'Independent source tokenization differs');helpers['bits'](projection(occ['scores']))
            if panel=='law':continue
            _,gold=helpers['coordinates'](source);target=source['canonical_ir']['rules'][0];row=dict(id=source['id'])
            for route,pred,success in (('raw',greedy,'decoded'),('joint',joint['result'],'selected')):
                ir=pred['canonical_ir'];require((pred['status']==success) is (ir is not None),'Status/IR association differs')
                if ir is not None:require(set(ir)=={'rules'} and len(ir['rules'])==1 and set(ir['rules'][0])=={'modality',*FIELDS},'Closed seven-field decoded IR required')
                row[route]=dict(full_IR=ir==source['canonical_ir'],**{f:ir is not None and ir['rules'][0][f]==target[f] for f in ('modality',*FIELDS)})
                require(row[route]['full_IR']==all(row[route][f] for f in ('modality',*FIELDS)),'Complete IR omitted a field')
            flags.append(row);cov.append(helpers['actor_coverage'](source,occ['scores'],gold))
        item=dict(state=state,panel=panel,rows=len(sources),reference_scored=panel!='law')
        if panel!='law':
            records[state,panel]=flags;coverage[state,panel]=cov
            item.update({route:{metric:sum(row[route][metric] for row in flags) for metric in ('full_IR','modality',*FIELDS)} for route in ('raw','joint')})
            item.update(actor_gold_coverage=helpers['coverage_summary'](cov),optional_presence_confusion=helpers['presence_recount'](sources,raw,chosen))
        panels.append(item)
    require(len(panels)==30 and len(records)==27,'Exact30panels/27scores required')
    for panel in (*PANELS,'training168'):
        raws=[loaded[state,panel][0] for state in STATES]
        for a,b,c in zip(*(value['occurrences'] for value in raws),strict=True):
            require(a['id']==b['id']==c['id'] and helpers['bits'](projection(a['scores']))==helpers['bits'](projection(b['scores'])),'Initial full632 binary32 parity differs')
            require(helpers['bits'](projection(a['scores'],False))==helpers['bits'](projection(c['scores'],False)),'Final632 modality/all-presence/nonactor binary32 parity differs')
        a,b=(loaded[state,panel] for state in ('parent','initial'))
        initial_prediction_parity(a[0]['inference']['rows'],b[0]['inference']['rows'],a[1],b[1])
    permissions={state:permission_recount(populations['old_tune'],*loaded[state,'old_tune']) for state in STATES}
    for phase,key in (('initial','initial_parity'),('trained','trained_parity')):
        receipt=read(frozen_descriptor(summary[key],freeze));require(receipt['passed'] is True and [c['name'] for c in receipt['controls']]==['zeros','alternate_placeholders','disabled','rotated_placeholders'],'All four dormant controls required');first=None
        for control in receipt['controls']:
            value=read(frozen_descriptor(control['report'],freeze));rows=[(helpers['bits'](projection(o['scores'])),g['canonical_ir'],g['status']) for o,g in zip(value['occurrences'],value['inference']['rows'],strict=True)]
            require(len(rows)==2 and (first is None or first==rows),'Dormant placeholders alter saved outputs');first=rows;newinference+=2
    require(newinference==runtime['actual_inference_source_forwards']==1280 and runtime['actual_model_forwards']==1312
        and runtime['actual_total_source_occurrences']==1664,'Actual1280/1312/1664 accounting differs')
    training=recount_training(read(frozen_descriptor(summary['training'],freeze)),populations['training168'],summary['prepared_schedule'])
    reported={(row['state'],row['panel']):row for row in analysis['panel_summaries']};require(len(reported)==len(analysis['panel_summaries'])==30 and set(reported)==set(captures),'Analyzer complete unique30 panels required')
    for item in panels:
        value=reported[item['state'],item['panel']];require(value['row_count']==item['rows'] and value['reference_scored']==item['reference_scored'],'Panel source scope differs')
        if not item['reference_scored']:require(value['raw_exact_ir'] is value['joint_exact_ir'] is None,'Law8 was scored');continue
        for route in ('raw','joint'):
            modal='modality_exact' if route=='raw' else 'joint_modality_exact';roles='role_exact_counts' if route=='raw' else 'joint_role_exact_counts'
            require(value[route+'_exact_ir']==item[route]['full_IR'] and value[modal]==item[route]['modality'] and value[roles]=={f:item[route][f] for f in FIELDS},'Independent completeIR/modality/six-role recount differs')
        require(value['actor_gold_coverage']==item['actor_gold_coverage'] and value['optional_presence_confusion']==item['optional_presence_confusion'],'Independent actor coverage/all-presence recount differs')
    paired={p:helpers['paired_score'](records['initial',p],records['trained',p]) for p in SCOPES}
    parentpaired={p:helpers['paired_score'](records['parent',p],records['trained',p]) for p in SCOPES}
    require(analysis['paired_initial_to_trained']==paired and analysis['paired_frozen_parent_to_trained']==parentpaired
        and analysis['all32_permission_retention']==permissions,'Every paired gain/loss and permission record must match')
    for panel in ('fresh_dev','fresh_test','training168'):
        ownpair=summary['parent_training_capture'] if panel=='training168' else summary['parent_fresh_panels'][panel]
        prior=ps['final_training_capture'] if panel=='training168' else ps['diagnostics'][panel]
        for view in ('raw','joint'):
            frozen_descriptor(ownpair[view],freeze)
            require({k:ownpair[view][k] for k in ('bytes','sha256')}=={k:prior[view][k] for k in ('bytes','sha256')},'Reused parent240 rows must retain exact frozen bytes')
    scientific=independent_acceptance(contract,records,permissions)
    require(analysis['scientific_acceptance']==scientific and analysis['scientific_success'] is scientific['scientific_success'],'Independent preregistered acceptance differs')
    ranks={p:[dict(id=a['id'],before_stable_rank=a['stable_rank'],after_stable_rank=b['stable_rank'],changed=a['stable_rank']!=b['stable_rank']) for a,b in zip(coverage['parent',p],coverage['trained',p],strict=True)] for p in SCOPES}
    for path,pin in list(OBSERVED.items()):identity(path,pin)
    result=dict(schema='actor-refinement-independent-recount/v1',passed=True,findings=[],recount_source=own,source_qualification=identity(QUALIFICATION),input_manifest=identity(INPUTS),
        freeze=inputs['freeze'],analysis=inputs['analysis'],runtime_review=freeze['runtime_review'],plan=freeze['plan'],panel_count=30,authored_score_sets=27,paired_panel_count=9,
        panels=panels,paired_initial_to_trained=paired,paired_frozen_parent_to_trained=parentpaired,scientific_acceptance=scientific,scientific_success=scientific['scientific_success'],
        actor_rank_changes=ranks,actor_rank_changes_are_diagnostics_only=True,all32_permission_retention=permissions,all632_initial_and_protected_heads_bit_equal=True,
        all32_training_traces_recounted=True,training=training,actual_new_inference_forwards=1280,actual_new_model_forwards=1312,total_new_source_occurrences=1664,
        copied_parent_capture_rows=240,new_parent_forwards=0,new_parent_updates=0,statutory8_unscored=True,full_IR_includes_modality=True,default_promotion=False,
        semantic_accuracy=None,latent_enabled=False,model_or_encoder_calls=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0,artifacts=OBSERVED)
    with OUTPUT.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    OUTPUT.chmod(0o444);print(identity(OUTPUT))


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Unqualified source-only F16 saved-score analysis; frozen N11 and F15 comparators.

Only pinned stdlib AST scoring/validation definitions are reused. Complete62
freeze and qualified public runtime precede all reference/result scoring. No
model, numerical import, checkpoint JSON, private resource body, network or Git.
"""
from __future__ import annotations
import argparse
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

ROOT=Path(__file__).resolve().parent
PURE_SOURCE=ROOT.parent/'legal-balanced-execution-20261014-01/analyze_conditions_balanced_v02.py'
PURE_SOURCE_PIN=dict(path=str(PURE_SOURCE),bytes=78492,sha256='1a4b4f6b579d0d086ef97d4867c9eea274ceb88142edb4bff849eb95f0fa2e57')
TRACE_SOURCE=ROOT/'review_actor_context_ranking_result_recount_v01.py'
TRACE_SOURCE_PIN=dict(path=str(TRACE_SOURCE),bytes=43889,sha256='d676f769c5d104fea600ff2036eb72146ab8f5f7519ee974835ce24812035601')
PURE_FUNCTIONS=('require','canonical','digest','pin','read','detached','source_projection','structural_validity',
    'private','fixed','descriptor','f32','binary','guarded_choice','expected_names','validate_freeze','bind','references',
    'span_ranking','span_coverage','hard_negative','gold_coverage','independent_score_checks','modality_summary',
    'failure_overlap','coverage_summary','panel_score','paired_changes','decoded_coupling','require_map_pin',
    'validate_capture_base','pure_predicates','compare_saved','optional_presence_confusion')
CONTRACT_PIN=dict(path=str(ROOT/'evaluation-contract-v01.json'),bytes=18389,sha256='26284be9473a9265659982067bf80a3d60ade49dd504b627d7866f7f09bb418d')
SOURCE_SHA='f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4'
SOURCE_STATE='a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'
F15=ROOT.parent/'legal-actor-refinement-20261014-01'
N11_SOURCE_SHA='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd'
N11_SOURCE_STATE='b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9'
STATES=('frozen_N11','parent','initial','trained')
FREEZE_PASSED=False
EXPECTED={}
OBSERVED={}
EARLY_READ_PATHS={ROOT/name for name in ('analyzer-source-independent-review-v01.json',
    'actor-context-ranking-output-freeze-v01.json','actor-context-ranking-hinge-runtime-review-v01.json','actor-context-ranking-hinge-plan-v01.json')}
sys.dont_write_bytecode=True


def bootstrap_source(path,expected):
    path=Path(path)
    if not path.is_absolute() or path.resolve(strict=True)!=path or path.is_symlink() or not path.is_file():
        raise ValueError('Physical ordinary immutable helper required')
    if any(p.is_symlink() for p in path.parents):raise ValueError('Symlink helper path refused')
    before=path.stat();raw=path.read_bytes();after=path.stat()
    stable=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if stable(before)!=stable(after) or len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:
        raise ValueError('Immutable helper source pin differs')
    return ast.parse(raw)


def load_pure_definitions():
    tree=bootstrap_source(PURE_SOURCE,PURE_SOURCE_PIN)
    constants={'N10','N11','N9','N8','N7','N6','N2','T','FIELDS','ALL_FIELDS','OLD_PANELS','FRESH_PANELS',
        'PANELS','COUNTS','MODALITIES','FALSE','EXPECTED','OBSERVED','FIXED'}
    assignments=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in PURE_FUNCTIONS]
    if len(functions)!=len(PURE_FUNCTIONS) or {n.name for n in functions}!=set(PURE_FUNCTIONS):raise ValueError('Exact immutable pure helper set required')
    if any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in functions):
        raise ValueError('Decorated/importing helper refused')
    exec(compile(ast.Module(body=assignments+functions,type_ignores=[]),str(PURE_SOURCE)+'#pure-only','exec'),globals())
    FIXED[ROOT/'evaluation-contract-v01.json']=(CONTRACT_PIN['bytes'],CONTRACT_PIN['sha256'])
    pin(PURE_SOURCE,PURE_SOURCE_PIN)


load_pure_definitions()
_pinned_read=read
_compare_saved_base=compare_saved


def read(path,expected=None):
    require(FREEZE_PASSED or Path(path) in EARLY_READ_PATHS,'Reference/result read before complete qualified freeze refused')
    return _pinned_read(path,expected)


def load_trace_helpers():
    """Common structural trace/criterion contract; scoring is independently recounted."""
    pin(TRACE_SOURCE,TRACE_SOURCE_PIN);tree=bootstrap_source(TRACE_SOURCE,TRACE_SOURCE_PIN)
    names={'require','digest','f32','ranked','denied_import','load_helpers','detached_definitions','load_training_validators',
           'projection','independent_acceptance','permission_recount','recount_training'}
    imports=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    require(all((n.module if isinstance(n,ast.ImportFrom) else n.names[0].name).split('.')[0] in sys.stdlib_module_names for n in imports),'Stdlib helper imports only')
    assignments=[n for n in tree.body if isinstance(n,ast.Assign)]
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes}==names and len(nodes)==len(names),'Exact structural trace helper set required')
    require(not any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in nodes),'Pure trace definitions required')
    namespace=dict(__file__=str(TRACE_SOURCE),identity=pin)
    exec(compile(ast.Module(body=imports+assignments+nodes,type_ignores=[]),str(TRACE_SOURCE)+'#structural-only','exec'),namespace)
    namespace['identity']=pin
    return namespace


def projection(scores,full=True):
    """Preserve ALL presence pairs and modality; only actor pointers may change."""
    require(type(full) is bool and set(scores['presence_logits'])==set(FIELDS[2:])
        and set(scores['start_logits'])==set(scores['end_logits'])==set(FIELDS)
        and len(scores['modality_logits'])==3,'Exact modality/four-presence/six-pointer geometry required')
    n=len(scores['tokens']);require(1<=n<=128,'Bounded token geometry required')
    require(all(len(v)==2 for v in scores['presence_logits'].values())
        and all(len(v)==n for side in ('start_logits','end_logits') for v in scores[side].values()),'Complete score vectors required')
    return dict(modality_logits=scores['modality_logits'],presence_logits=dict(scores['presence_logits']),
        **{side:{role:value for role,value in scores[side].items() if full or role!='actor'} for side in ('start_logits','end_logits')})


def compare_saved(rows,before,after,*,full,before_joint=None,after_joint=None):
    records=_compare_saved_base(rows,before,after,full=full,before_joint=before_joint,after_joint=after_joint)
    if full and before_joint is not None:
        require(before_joint==after_joint,'Initial COMPLETE joint row envelopes differ')
    return records


def validate_joint(value,raw,rows,joint):
    require(value['schema'] in {'actor-context-ranking-joint-panel/v1','actor-refinement-joint-panel/v1','conditions-presence-joint-panel/v1'}
        and value['top_k']==8 and value['max_search_nodes']==50000 and len(value['rows'])==len(rows),'Closed F15/N11 joint schema and bounded geometry required')
    for src,occ,row in zip(rows,raw['occurrences'],value['rows'],strict=True):
        require(src['id']==row['id'] and row['result']==joint['select_joint_spans'](src['source_text'],occ['scores'],top_k=8,max_search_nodes=50000),'Saved pure joint replay differs')
    return value['rows']


def validate_capture(raw,rows,greedy,joint,*,candidate=False,summary=None,report=None,state=None,latent='none',comparator='parent'):
    validate_capture_base(raw,rows,greedy,joint)
    inference=raw['inference'];n=len(rows)
    require(1<=n<=168,'Bounded complete capture rows required')
    if not candidate:
        require(comparator in ('parent','frozen_N11'),'Closed frozen comparator required')
        prefix,sha,state_hash=(('actor-refinement',SOURCE_SHA,SOURCE_STATE) if comparator=='parent'
            else ('conditions-presence',N11_SOURCE_SHA,N11_SOURCE_STATE))
        require(raw['schema']==prefix+'-adapter-target-free-head-capture/v1'
            and inference['schema']=='bounded-'+prefix+'-adapter-inference/v1'
            and inference['checkpoint_sha256']==sha and inference['model_state_sha256']==state_hash,
            'Exact frozen comparator capture identity required')
        return
    require(raw['schema']=='actor-context-ranking-adapter-target-free-head-capture/v1'
        and inference['schema']=='bounded-actor-context-ranking-adapter-inference/v1','Closed F16 target-free capture schemas required')
    require(state in ('initial','trained') and inference['checkpoint_sha256']==(summary['initial_checkpoint_sha256'] if state=='initial' else summary['checkpoint']['sha256'])
        and inference['model_state_sha256']==summary['initial_model_state_sha256' if state=='initial' else 'final_model_state_sha256']
        and inference['source_actor_refinement_checkpoint_sha256']==SOURCE_SHA
        and inference['source_actor_refinement_model_state_sha256']==SOURCE_STATE and inference['source_actor_refinement_optimizer_steps']==32
        and inference['latent_ablation']==latent and inference['feature_paths_per_source_forward']==3
        and inference['branch_digests']==report['initial_branch_digests' if state=='initial' else 'final_branch_digests']
        and inference['training_policy']==report['training_policy'] and inference['training_policy_sha256']==digest(report['training_policy']),
        'Exact F15 continuation capture lineage/policy differs')
    for key in ('source_model_forwards','actor_features_model_forwards','frozen_modality_encoder_forwards',
        'frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'):
        require(raw[key]==inference[key]==n,'Actual candidate same-forward module accounting differs')


def decoded_coupling(before,after,before_joint,after_joint):
    """Report selector coupling and abstention changes without a semantic veto."""
    result={}
    for route,old,new in [('raw',before['inference']['rows'],after['inference']['rows']),
        ('joint',[r['result'] for r in before_joint],[r['result'] for r in after_joint])]:
        status=[];changed={field:[] for field in ALL_FIELDS};selected_changed={field:[] for field in ALL_FIELDS}
        for occurrence,a,b in zip(before['occurrences'],old,new,strict=True):
            if a['status']!=b['status']:status.append(occurrence['id'])
            left=None if a['canonical_ir'] is None else a['canonical_ir']['rules'][0]
            right=None if b['canonical_ir'] is None else b['canonical_ir']['rules'][0]
            for field in ALL_FIELDS:
                if (None if left is None else left[field])!=(None if right is None else right[field]):
                    changed[field].append(occurrence['id'])
                    if left is not None and right is not None:selected_changed[field].append(occurrence['id'])
        result[route]=dict(status_changed_ids=status,
            field_value_changes_including_abstention={field:dict(count=len(ids),ids=ids) for field,ids in changed.items()},
            field_value_changes_when_both_selected={field:dict(count=len(ids),ids=ids) for field,ids in selected_changed.items()})
    return result


def scientific_acceptance(contract,records,permissions):
    """Fixed four-state acceptance; negative science remains a reportable outcome."""
    required=tuple(p for p in (*PANELS,'training168') if p!='law')
    require(tuple(contract['states'])==STATES and tuple(contract['paired_scored_scopes'])==required,
        'Exact four-state/nine-scope contract required')
    criterion=contract['strict_scientific_success']
    require(criterion['training168']['minimum_accepted_raw_and_joint']==155
        and criterion['training168']['raw_full_IR_strictly_greater_than']==criterion['training168']['joint_full_IR_strictly_greater_than']==154
        and criterion['permission_retention']['gold_permission_count']==32
        and criterion['permission_retention']['allowed_losses']==criterion['permission_retention']['allowed_abstentions']==0,
        'Fixed155/zero-loss/all32-permission criterion required')
    for name in ('N11','F15'):
        rule=criterion['no_complete_IR_loss_IDs_vs_'+name]
        require(rule['allowed_loss_count_each_scope_and_view']==0 and tuple(rule['scopes'])==required
            and rule['views']==['raw','joint'],'Both exact frozen comparator criteria required')
    require(set(records)=={(s,p) for s in STATES for p in required},'Complete36 score records required')
    for state in STATES:
        for panel in required:
            rows=records[state,panel]
            require(len(rows)==len({r['id'] for r in rows})==(168 if panel=='training168' else COUNTS[panel])
                and all(type(r[v+'_exact_ir']) is bool for r in rows for v in ('raw','joint')),
                'Complete unique typed source score records required')
    comparisons={}
    for label,state in (('N11','frozen_N11'),('F15','parent')):
        losses={}
        for panel in required:
            before,after=records[state,panel],records['trained',panel]
            require([r['id'] for r in before]==[r['id'] for r in after],'Ordered comparator/trained source IDs required')
            losses[panel]={v:[a['id'] for a,b in zip(before,after,strict=True) if a[v+'_exact_ir'] and not b[v+'_exact_ir']]
                for v in ('raw','joint')}
        comparisons[label]=dict(views=['raw','joint'],scopes=list(required),loss_ids_by_scope=losses,
            passed=not any(ids for value in losses.values() for ids in value.values()))
    train={v+'_full_IR':sum(r[v+'_exact_ir'] for r in records['trained','training168']) for v in ('raw','joint')}
    train.update(minimum_required=155,passed=all(value>=155 for value in train.values()))
    require(set(permissions)==set(STATES),'All four permission states required')
    permission_pass=all(p['count']==len(p['ids'])==len(set(p['ids']))==32 and p['raw_P_to_P']==p['joint_P_to_P']==32
        and p['losses']==p['abstentions']==0 for p in permissions.values())
    return dict(schema='actor-context-ranking-scientific-acceptance/v1',technical_gate_passed=True,training168=train,
        no_complete_IR_loss_IDs_vs_N11=comparisons['N11'],no_complete_IR_loss_IDs_vs_F15=comparisons['F15'],
        all32_permission_retention=dict(count=32,passed=permission_pass),
        scientific_success=train['passed'] and all(v['passed'] for v in comparisons.values()) and permission_pass)


def main(args):
    global FREEZE_PASSED
    output=Path(args.output);require(output==ROOT/'actor-context-ranking-result-analysis-v01.json' and not os.path.lexists(output),'Exclusive owned analysis output required')
    own=pin(Path(__file__).resolve());approval_pin=pin(ROOT/'analyzer-source-independent-review-v01.json');approval=read(approval_pin['path'],approval_pin)
    require(approval['schema']=='actor-context-ranking-analyzer-source-independent-review/v1' and approval['passed'] is True
        and approval['findings']==[] and approval['analyzer']==own,'Exact independently qualified analyzer required')
    for value in (own,PURE_SOURCE_PIN,TRACE_SOURCE_PIN,CONTRACT_PIN):require_map_pin(approval['artifacts'],value)
    freeze_pin=descriptor(dict(path=str(Path(args.freeze)),bytes=args.freeze_bytes,sha256=args.freeze_sha256))
    require(freeze_pin['path']==str(ROOT/'actor-context-ranking-output-freeze-v01.json'),'Exact actor-context-ranking freeze required')
    freeze=read(freeze_pin['path'],freeze_pin);result_root=validate_freeze(freeze,freeze_pin['path'],schema='actor-context-ranking-output-freeze/v1')
    runtime_pin=descriptor(freeze['runtime_review']);runtime=read(runtime_pin['path'],runtime_pin)
    require(runtime_pin['path']==str(ROOT/'actor-context-ranking-hinge-runtime-review-v01.json') and runtime['schema']=='actor-context-ranking-runtime-independent-review/v1'
        and runtime['passed'] is True and runtime['findings']==[] and runtime['outputs']==freeze['results'] and runtime['output_file_count']==62,'Complete qualified runtime/output closure required')
    require_map_pin(approval['artifacts'],runtime['observer'])
    plan_pin=descriptor(freeze['plan']);require_map_pin(approval['artifacts'],plan_pin);plan=read(plan_pin['path'],plan_pin)
    require(plan_pin['path']==str(ROOT/'actor-context-ranking-hinge-plan-v01.json') and plan['schema']=='actor-context-ranking-cell-plan/v1'
        and plan['cell']=='actor-context-ranking-hinge' and plan['source_checkpoint']['sha256']==SOURCE_SHA and plan['source_model_state_sha256']==SOURCE_STATE
        and plan['evaluation_contract']==freeze['evaluation_contract']==CONTRACT_PIN and plan['latent_enabled'] is plan['default_promotion'] is False
        and runtime['plan']==plan_pin and len(plan['source_owner_pins'])==40,'Exact trained N11 source-only continuation plan required')
    require((runtime['actual_returned_optimizer_updates'],runtime['actual_training_source_occurrences'],runtime['actual_inference_source_forwards'],
        runtime['actual_model_forwards'],runtime['actual_total_source_occurrences'])==(32,384,1280,1312,1664),'Actual source/forward accounting differs')
    EARLY_READ_PATHS.add(Path(freeze['summary']['path']));summary=bind(freeze['summary'],freeze,result_root,'summary.json')
    require(summary['schema']=='actor-context-ranking-cell-results/v1' and summary['status']=='completed' and summary['cell']=='actor-context-ranking-hinge'
        and summary['opening_owners']==summary['closing_owners'] and len(summary['opening_owners'])==plan['expected_loaded_owner_count']
        and all(v==plan['source_owner_pins'].get(k) for k,v in summary['opening_owners'].items())
        and summary['candidate_training_capture_call_sizes']==summary['parent_training_capture_call_sizes']==[128,40],'Completed source-bound measured-loaded/40-owner-plus-supplement summary required')
    FREEZE_PASSED=True
    contract=read(CONTRACT_PIN['path'],CONTRACT_PIN)
    require(contract['schema']=='actor-context-ranking-evaluation-contract/v1' and contract['law8_unscored'] is True
        and (contract['expected_panel_count'],contract['expected_authored_score_sets'],contract['expected_paired_panel_count'])==(40,36,18),'Closed exposed-diagnostic scope differs')
    for path,value in approval['artifacts'].items():pin(path,value)
    namespace,greedy,joint,scorer=pure_predicates(plan);namespace.update(plan=plan,summary=summary)
    data,populations,metadata=references(plan);rows=data['training_rows'];trace=load_trace_helpers()
    report=bind(summary['training'],freeze,result_root,'cell-training.json');training=trace['recount_training'](report,rows,summary['prepared_schedule'])
    require(report['checkpoint_sha256']==summary['checkpoint']['sha256'] and report['final_model_state_sha256']==summary['final_model_state_sha256'],'Training result/checkpoint raw descriptor joins differ')
    comparator_inputs=read(contract['postfreeze_comparator_inputs']['path'],contract['postfreeze_comparator_inputs'])
    require(comparator_inputs['schema']=='actor-context-ranking-postfreeze-comparator-inputs/v1'
        and comparator_inputs['states']==list(STATES)
        and all(comparator_inputs[k]==contract[k] for k in ('completed_frozen_parent','completed_frozen_N11','source_parent',
            'source_model_state_sha256','source_export','fresh_source_export','fresh_reference_packet','fresh_reference_review')),
        'Exact postfreeze comparator-input custody required')
    comparator_sources={}
    for label,key,prefix,metadata_root,sha,state_hash in (
        ('parent','completed_frozen_parent','actor-refinement',F15,SOURCE_SHA,SOURCE_STATE),
        ('frozen_N11','completed_frozen_N11','conditions-presence',N11,N11_SOURCE_SHA,N11_SOURCE_STATE)):
        pc=contract[key];review=read(pc['independent_review']['path'],pc['independent_review'])
        pf=read(pc['freeze']['path'],pc['freeze']);pr=read(pc['runtime_review']['path'],pc['runtime_review'])
        require(review['schema']==prefix+'-result-independent-review/v1' and review['passed'] is True and review['findings']==[]
            and review['freeze']==pc['freeze'] and review['plan']==pc['plan']
            and pc['new_control_forwards']==pc['new_control_updates']==0
            and pr['schema']==prefix+'-runtime-independent-review/v1' and pr['passed'] is True and pr['findings']==[]
            and pr['outputs']==pf['results'],'Exact frozen comparator custody required')
        cr=validate_freeze(pf,pc['freeze']['path'],metadata_root=metadata_root,schema=prefix+'-output-freeze/v1')
        ps=bind(pf['summary'],pf,cr,'summary.json')
        require(ps['checkpoint']['sha256']==sha and ps['final_model_state_sha256']==state_hash,'Exact comparator model identity required')
        if label=='parent':require(ps['checkpoint']==plan['source_checkpoint']==contract['source_parent'],'Exact F15 donor differs')
        comparator_sources[label]=(pf,cr,ps)
    actual={};new_inference=0
    def pair(descriptors,source_rows,label,state):
        nonlocal new_inference
        require(descriptors['row_count']==len(source_rows),'Capture source scope differs')
        raw=bind(descriptors['raw'],freeze,result_root,label+'-raw.json');validate_capture(raw,source_rows,greedy,joint,candidate=True,summary=summary,report=report,state=state)
        chosen=validate_joint(bind(descriptors['joint'],freeze,result_root,label+'-joint.json'),raw,source_rows,joint);new_inference+=len(source_rows);return raw,chosen
    for state,key,prefix in [('initial','baseline_panels','baseline-'),('trained','diagnostics','trained-')]:
        require(set(summary[key])==set(PANELS),'Complete candidate panel set required')
        for panel in PANELS:actual[state,panel]=pair(summary[key][panel],source_projection(populations[panel]),prefix+panel,state)
        key,label=('initial_training_capture','initial-training168') if state=='initial' else ('final_training_capture','trained-training168')
        actual[state,'training168']=pair(summary[key],rows,label,state)
    copied={}
    for comparator,(parent_freeze,parent_root,parent_summary) in comparator_sources.items():
        for panel in (*PANELS,'training168'):
            sr=rows if panel=='training168' else source_projection(populations[panel])
            descriptors=parent_summary['final_training_capture'] if panel=='training168' else parent_summary['diagnostics'][panel]
            label='trained-training168' if panel=='training168' else 'trained-'+panel
            raw=bind(descriptors['raw'],parent_freeze,parent_root,label+'-raw.json')
            validate_capture(raw,sr,greedy,joint,comparator=comparator)
            chosen=validate_joint(bind(descriptors['joint'],parent_freeze,parent_root,label+'-joint.json'),raw,sr,joint)
            actual[comparator,panel]=raw,chosen
            if comparator=='parent' and panel in (*FRESH_PANELS,'training168'):
                ownpair=summary['parent_training_capture'] if panel=='training168' else summary['parent_fresh_panels'][panel]
                ownlabel='parent-training168' if panel=='training168' else 'parent-'+panel
                for view in ('raw','joint'):
                    bind(ownpair[view],freeze,result_root,ownlabel+'-'+view+'.json')
                    require({k:ownpair[view][k] for k in ('bytes','sha256')}=={k:descriptors[view][k] for k in ('bytes','sha256')},
                        'Copied F15 parent bytes differ from authenticated frozen source')
                    copied[ownlabel+'-'+view]=dict(source=descriptors[view],copy=ownpair[view],new_forward_calls=0)
    require(len(copied)==6,'Exactly six saved parent copies required')
    initial={};protected={}
    for panel in (*PANELS,'training168'):
        sr=rows if panel=='training168' else source_projection(populations[panel]);parent,first,last=(actual[s,panel] for s in ('parent','initial','trained'))
        initial[panel]=compare_saved(sr,parent[0],first[0],full=True,before_joint=parent[1],after_joint=first[1])
        protected[panel]=compare_saved(sr,parent[0],last[0],full=False)
    require(sum(map(len,initial.values()))==sum(map(len,protected.values()))==632,'Full632 parity/protection scope required')
    dormant=[]
    for phase,key in [('initial','initial_parity'),('trained','trained_parity')]:
        receipt=bind(summary[key],freeze,result_root,phase+'-parity.json');first=None
        require(receipt['passed'] is True and receipt['actual_encoder_calls']==0 and receipt['genuine_latent_semantics_tested'] is False
            and [c['name'] for c in receipt['controls']]==['zeros','alternate_placeholders','disabled','rotated_placeholders'],'Exact dormant-only controls required')
        for item in receipt['controls']:
            sr=deepcopy(source_projection(populations['fresh_tune'][:2]))
            for i,row in enumerate(sr):row['latent']=[0. if item['name']=='zeros' else .25 if i==0 else -.25]*384
            if item['name']=='rotated_placeholders':sr[0]['latent'],sr[1]['latent']=sr[1]['latent'],sr[0]['latent']
            raw=bind(item['report'],freeze,result_root,phase+'-parity-'+item['name']+'.json');validate_capture(raw,sr,greedy,joint,candidate=True,summary=summary,report=report,state=phase,latent=item['control'])
            value=[dict(heads=binary(projection(o['scores'])).hex(),status=g['status'],canonical_ir=g['canonical_ir']) for o,g in zip(raw['occurrences'],raw['inference']['rows'],strict=True)]
            require(first is None or value==first,'Dormant placeholders altered readout');first=value;new_inference+=2
        dormant.append(dict(phase=phase,controls=4,rows_each=2,invariant=True,genuine_latent_semantics_tested=False))
    require(new_inference==1280,'Exactly1280 new inference occurrences required')
    summaries=[];scores={};coverage={}
    for state in STATES:
        for panel in (*PANELS,'training168'):
            src=rows if panel=='training168' else populations[panel];meta=data['training_metadata'] if panel=='training168' else metadata.get(panel)
            compact,records,cov=panel_score(panel,state,src,meta,*actual[state,panel],scorer,namespace,joint);summaries.append(compact)
            if records is not None:scores[state,panel]=records;coverage[state,panel]=cov
    require(len(summaries)==40 and len(scores)==36,'Exact40panels/36scores required')
    paired={};parentpaired={};n11paired={};coupling={};ranks={}
    for panel in contract['paired_scored_scopes']:
        paired[panel]=paired_changes(scores['initial',panel],scores['trained',panel]);parentpaired[panel]=paired_changes(scores['parent',panel],scores['trained',panel])
        n11paired[panel]=paired_changes(scores['frozen_N11',panel],scores['trained',panel])
        coupling[panel]=decoded_coupling(actual['parent',panel][0],actual['trained',panel][0],actual['parent',panel][1],actual['trained',panel][1])
        ranks[panel]=[dict(id=a['id'],before_stable_rank=a['stable_rank'],after_stable_rank=b['stable_rank'],changed=a['stable_rank']!=b['stable_rank']) for a,b in zip(coverage['parent',panel],coverage['trained',panel],strict=True)]
    permissions={state:trace['permission_recount'](populations['old_tune'],*actual[state,'old_tune']) for state in STATES}
    require(all(sum(r[view+'_exact_ir'] for r in scores[state,'training168'])==154
        for state in ('parent','frozen_N11') for view in ('raw','joint')),'Both frozen training154 baselines required')
    scientific=scientific_acceptance(contract,scores,permissions)
    for path,expected in list(OBSERVED.items()):pin(path,expected)
    result=dict(schema='actor-context-ranking-exposed-result-analysis/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        analyzer=own,independent_source_review=approval_pin,freeze=freeze_pin,runtime_review=runtime_pin,plan=plan_pin,evaluation_contract=CONTRACT_PIN,
        panel_count=40,authored_score_sets=36,paired_panel_count=18,panel_summaries=summaries,paired_initial_to_trained=paired,
        paired_frozen_parent_to_trained=parentpaired,paired_frozen_N11_to_trained=n11paired,scientific_acceptance=scientific,scientific_success=scientific['scientific_success'],
        actor_rank_changes=ranks,actor_rank_changes_are_diagnostics_only=True,decoded_other_role_coupling=coupling,training_metadata=training,
        initial_full_head_parity=dict(rows=632,all_binary32_components_equal=True),
        final_protected_head_retention=dict(rows=632,all_required_binary32_components_equal=True,excluded_components_only=['start_logits.actor','end_logits.actor'],all_four_presence_pairs_protected=True),
        all32_permission_retention=permissions,copied_parent_captures=copied,copied_parent_capture_rows=240,copied_parent_new_forwards=0,
        dormant_controls=dormant,actual_new_inference_forwards=1280,actual_new_model_forwards=1312,training_source_occurrences=384,total_new_source_occurrences=1664,
        new_parent_control_updates=0,new_parent_control_forwards=0,new_N11_control_updates=0,new_N11_control_forwards=0,external_embedding_encoder_calls=0,feature_paths_per_candidate_forward=3,
        statutory8_unscored=True,all_panels_previously_exposed_diagnostics=True,full_IR_includes_modality=True,default_promotion=False,semantic_accuracy=None,
        Lake_executed=False,broader_logic_families_qualified=False,genuine_latent_semantics_qualified=False,portable_numerical_reload_proven=False,
        checkpoint_JSON_parses=0,model_or_encoder_calls=0,private_body_reads=0,resource_API_calls=0,network_calls=0,Git_mutations=0,input_pins=OBSERVED)
    with output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    output.chmod(0o444);print(pin(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--freeze',required=True);parser.add_argument('--freeze-bytes',required=True,type=int)
    parser.add_argument('--freeze-sha256',required=True);parser.add_argument('--output',required=True);main(parser.parse_args())

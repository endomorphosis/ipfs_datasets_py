"""Author source-only F16 evaluator ports. No saved-result/reference/model reads."""
import ast, hashlib, json, re
from pathlib import Path
F=Path(__file__).resolve().parent
P=F.parent/'legal-actor-refinement-20261014-01'
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def replace_function(src,name,replacement):
 node=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name==name)
 lines=src.splitlines(keepends=True)
 return ''.join(lines[:node.lineno-1])+replacement.rstrip()+'\n'+''.join(lines[node.end_lineno:])
def once(src,old,new):
 if src.count(old)!=1:raise ValueError('Expected one derivation anchor: '+old[:120])
 return src.replace(old,new,1)
contract=pin(F/'evaluation-contract-v01.json')
comparators=pin(F/'postfreeze-comparator-inputs-v01.json')
model=pin(F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_context_ranking.py')
originals={
 'analyze_actor_refinement_v01.py':(28064,'6c6309903cbe20ea73d045e6d29224096ff3a8602cc935c0af6343a6f4599d1b'),
 'review_actor_refinement_result_recount_v01.py':(41111,'e60814cdf89c0fa3d90dd732a4d6fd9e05dd9ea2a27834910fddf7dcbeaa0692')}
for name,(size,sha) in originals.items():
 d=pin(P/name)
 if (d['bytes'],d['sha256'])!=(size,sha):raise ValueError('Retained source differs')
def initial(name):
 s=(P/name).read_text().replace('actor-refinement','actor-context-ranking').replace('actor_refinement','actor_context_ranking')
 s=s.replace("STATES = ('parent','initial','trained')","STATES = ('frozen_N11','parent','initial','trained')")
 s=s.replace("STATES=('parent','initial','trained')","STATES=('frozen_N11','parent','initial','trained')")
 s=s.replace("bytes=12913,sha256='a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e'",f"bytes={contract['bytes']},sha256='{contract['sha256']}'")
 s=s.replace("bytes=12913, sha256='a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e'",f"bytes={contract['bytes']}, sha256='{contract['sha256']}'")
 s=s.replace('source_conditions_presence','source_actor_refinement')
 s=s.replace('34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd','f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
 s=s.replace('b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9','a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42')
 s=s.replace('actor-context-ranking-ce','actor-context-ranking-hinge')
 s=s.replace('actor-context-ranking-hingell','actor-context-ranking-cell')
 return s
criterion_analyzer='''def scientific_acceptance(contract,records,permissions):
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
'''
criterion_recount='''def independent_acceptance(contract,records,permissions,technical_passed=True):
    """Separate row-shape recount, same author as analyzer; peer review required."""
    require(type(technical_passed) is bool and tuple(contract['states'])==STATES
        and tuple(contract['paired_scored_scopes'])==SCOPES,'Exact four-state/nine-scope criterion required')
    criterion=contract['strict_scientific_success']
    require(criterion['training168']['minimum_accepted_raw_and_joint']==155
        and criterion['training168']['raw_full_IR_strictly_greater_than']==154
        and criterion['training168']['joint_full_IR_strictly_greater_than']==154
        and criterion['permission_retention']['gold_permission_count']==32
        and criterion['permission_retention']['allowed_losses']==criterion['permission_retention']['allowed_abstentions']==0,
        'Fixed preregistered155/zero-loss/all32-permission criterion required')
    for label in ('N11','F15'):
        rule=criterion['no_complete_IR_loss_IDs_vs_'+label]
        require(rule['allowed_loss_count_each_scope_and_view']==0 and tuple(rule['scopes'])==SCOPES
            and rule['views']==['raw','joint'],'Both exact frozen comparison scopes required')
    require(set(records)=={(s,p) for s in STATES for p in SCOPES},'Complete36 authored score scopes required')
    require(all(len(records[s,p])==len({r['id'] for r in records[s,p]})==COUNTS[p]
        and all(type(r[v]['full_IR']) is bool for r in records[s,p] for v in ('raw','joint'))
        for s in STATES for p in SCOPES),'Complete unique typed score rows required')
    comparisons={}
    for label,state in (('N11','frozen_N11'),('F15','parent')):
        loss_ids={}
        for panel in SCOPES:
            before,after=records[state,panel],records['trained',panel]
            require([r['id'] for r in before]==[r['id'] for r in after],'Complete ordered unique paired IDs required')
            loss_ids[panel]={v:[a['id'] for a,b in zip(before,after,strict=True) if a[v]['full_IR'] and not b[v]['full_IR']]
                for v in ('raw','joint')}
        comparisons[label]=dict(views=['raw','joint'],scopes=list(SCOPES),loss_ids_by_scope=loss_ids,
            passed=not any(ids for value in loss_ids.values() for ids in value.values()))
    train={v+'_full_IR':sum(r[v]['full_IR'] for r in records['trained','training168']) for v in ('raw','joint')}
    train.update(minimum_required=155,passed=all(value>=155 for value in train.values()))
    require(set(permissions)==set(STATES),'All four permission states required')
    retained=dict(count=32,passed=all(p['count']==len(p['ids'])==len(set(p['ids']))==32
        and p['raw_P_to_P']==p['joint_P_to_P']==32 and p['losses']==p['abstentions']==0 for p in permissions.values()))
    return dict(schema='actor-context-ranking-scientific-acceptance/v1',technical_gate_passed=technical_passed,
        training168=train,no_complete_IR_loss_IDs_vs_N11=comparisons['N11'],no_complete_IR_loss_IDs_vs_F15=comparisons['F15'],
        all32_permission_retention=retained,
        scientific_success=technical_passed and train['passed'] and all(v['passed'] for v in comparisons.values()) and retained['passed'])
'''
# Recount source keeps seven immutable F14 helpers and F15 structural trace logic.
r=initial('review_actor_refinement_result_recount_v01.py')
r=r.replace('independent stdlib F15 recount','separate stdlib F16 recount (same author as analyzer)')
r=r.replace("bytes=56952,sha256='a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'",f"bytes={model['bytes']},sha256='{model['sha256']}'")
r=replace_function(r,'independent_acceptance',criterion_recount)
r=r.replace('actor_ranking_enabled=False,presence_ce_weight=1','actor_ranking_enabled=True,presence_ce_weight=1')
r=r.replace('Trained N11','Trained F15').replace('trained N11','trained F15')
r=once(r,"frozen=report['source_frozen36_state_sha256'];inactive=report['inactive_head_rows_sha256_initial']",
 "frozen=report['source_frozen36_state_sha256'];inactive=report['inactive_head_rows_sha256_initial']\n    require(frozen=='6d367a28a38e7244fddcd60ec0db137f3c534c0363fb993fe7b28678d2261507','Exact learned F15 frozen36 source digest required')")
r=once(r,"and base['present_gold_nonactor_coordinates']==nonactor,'Every one of384 source/gold actor and nonactor-domain joins required')",
 "and base['present_gold_nonactor_coordinates']==nonactor\n                and row['source_sha256']==base['source_sha256']\n                and row['present_gold_nonactor_coordinates']==nonactor\n                and row['compatible_wrong_candidate_count']==base['compatible_wrong_candidate_count']\n                and row['compatible_wrong_domain_sha256']==base['compatible_wrong_domain_sha256'],\n                'Every one of384 source/gold actor and nonactor-domain joins required')")
r=r.replace("independent_numerical_gradient_proof=False,scalar_CE_recomputed=False)",
 "independent_numerical_gradient_proof=False,scalar_CE_recomputed=False,\n        independent_complete_preupdate_argmax_replay=False,selected_scalar_hinge_and_filtered_domain_replayed=True)")
r=once(r,"(analysis['panel_count'],analysis['authored_score_sets'],analysis['paired_panel_count'])==(30,27,9)",
 "(analysis['panel_count'],analysis['authored_score_sets'],analysis['paired_panel_count'])==(40,36,18)")
begin=r.index("    populations=load_populations(plan,contract);parent=contract['completed_frozen_parent']")
end=r.index("    loaded={};panels=[];records={};coverage={};newinference=0",begin)
r=r[:begin]+'''    comparator_inputs=read(contract['postfreeze_comparator_inputs'])
    require(comparator_inputs['schema']=='actor-context-ranking-postfreeze-comparator-inputs/v1'
        and comparator_inputs['states']==list(STATES)
        and all(comparator_inputs[k]==contract[k] for k in ('completed_frozen_parent','completed_frozen_N11','source_parent',
            'source_model_state_sha256','source_export','fresh_source_export','fresh_reference_packet','fresh_reference_review')),
        'Exact postfreeze comparator-input custody required')
    populations=load_populations(plan,contract)
    comparator_freezes={};comparator_summaries={}
    for label,key,prefix,sha,state_hash in (
        ('parent','completed_frozen_parent','actor-refinement','f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4','a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'),
        ('frozen_N11','completed_frozen_N11','conditions-presence','34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd','b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9')):
        parent=contract[key];pf=read(parent['freeze']);pr=read(parent['runtime_review'])
        authenticate_freeze(pf,pr,prefix+'-output-freeze/v1');review=read(parent['independent_review'])
        require(review['passed'] is True and review['findings']==[] and review['freeze']==parent['freeze'] and review['plan']==parent['plan']
            and parent['new_control_forwards']==parent['new_control_updates']==0,'Frozen comparator custody required')
        ps=read(pf['summary'])
        require(ps['checkpoint']['sha256']==sha and ps['final_model_state_sha256']==state_hash,'Exact frozen comparator model required')
        if label=='parent':require(ps['checkpoint']==plan['source_checkpoint'],'F15 donor checkpoint differs')
        comparator_freezes[label]=pf;comparator_summaries[label]=ps
    captures={(state,p):summary['baseline_panels' if state=='initial' else 'diagnostics'][p] for state in ('initial','trained') for p in PANELS}
    for state in ('initial','trained'):captures[state,'training168']=summary['initial_training_capture' if state=='initial' else 'final_training_capture']
    for label,ps in comparator_summaries.items():
        for p in PANELS:captures[label,p]=ps['diagnostics'][p]
        captures[label,'training168']=ps['final_training_capture']
    ps=comparator_summaries['parent']
''' +r[end:]
r=r.replace("custody=pf if state=='parent' else freeze","custody=comparator_freezes[state] if state in comparator_freezes else freeze")
r=r.replace("if state!='parent':newinference+=len(sources)","if state in ('initial','trained'):newinference+=len(sources)")
r=r.replace("len(panels)==30 and len(records)==27","len(panels)==40 and len(records)==36")
r=r.replace("'Exact30panels/27scores required'","'Exact40panels/36scores required'")
r=r.replace("raws=[loaded[state,panel][0] for state in STATES]","raws=[loaded[state,panel][0] for state in ('parent','initial','trained')]")
r=r.replace("==30 and set(reported)==set(captures)","==40 and set(reported)==set(captures)")
r=r.replace("'Analyzer complete unique30 panels required'","'Analyzer complete unique40 panels required'")
r=once(r,"    parentpaired={p:helpers['paired_score'](records['parent',p],records['trained',p]) for p in SCOPES}",
 "    parentpaired={p:helpers['paired_score'](records['parent',p],records['trained',p]) for p in SCOPES}\n    n11paired={p:helpers['paired_score'](records['frozen_N11',p],records['trained',p]) for p in SCOPES}")
r=r.replace("and analysis['all32_permission_retention']==permissions","and analysis['paired_frozen_N11_to_trained']==n11paired\n        and analysis['all32_permission_retention']==permissions")
r=r.replace("panel_count=30,authored_score_sets=27,paired_panel_count=9","panel_count=40,authored_score_sets=36,paired_panel_count=18")
r=r.replace("panels=panels,paired_initial_to_trained=paired,paired_frozen_parent_to_trained=parentpaired,",
 "panels=panels,paired_initial_to_trained=paired,paired_frozen_parent_to_trained=parentpaired,paired_frozen_N11_to_trained=n11paired,")
r=r.replace("copied_parent_capture_rows=240,new_parent_forwards=0,new_parent_updates=0,",
 "copied_parent_capture_rows=240,new_parent_forwards=0,new_parent_updates=0,new_N11_forwards=0,new_N11_updates=0,\n        same_author_as_primary_analyzer=True,independent_peer_actual_review_still_required=True,")
r=r.replace("'Exact30/27/9 analysis joins required'","'Exact40/36/18 analysis joins required'")
# Explicitly verify frozen baseline154 without extra thresholds.
r=once(r,"    scientific=independent_acceptance(contract,records,permissions)",
 "    require(all(sum(row[v]['full_IR'] for row in records[s,'training168'])==154\n        for s in ('parent','frozen_N11') for v in ('raw','joint')),'Both frozen training154 baselines required')\n    scientific=independent_acceptance(contract,records,permissions)")
rp=F/'review_actor_context_ranking_result_recount_v01.py'
compile(r,str(rp),'exec')
with rp.open('x') as h:h.write(r)
tracepin=pin(rp)
# Analyzer is a thin F15 port using the exact new recount source only for trace validation.
a=initial('analyze_actor_refinement_v01.py')
a=a.replace('Source-qualified F15 saved-score analysis; sole trained N11 frozen comparator.','Unqualified source-only F16 saved-score analysis; frozen N11 and F15 comparators.')
a=a.replace("bytes=41111,sha256='e60814cdf89c0fa3d90dd732a4d6fd9e05dd9ea2a27834910fddf7dcbeaa0692'",f"bytes={tracepin['bytes']},sha256='{tracepin['sha256']}'")
a=a.replace("SOURCE_STATE='a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'",
 "SOURCE_STATE='a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'\nF15=ROOT.parent/'legal-actor-refinement-20261014-01'\nN11_SOURCE_SHA='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd'\nN11_SOURCE_STATE='b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9'")
a=a.replace("'actor-context-ranking-joint-panel/v1','conditions-presence-joint-panel/v1'",
 "'actor-context-ranking-joint-panel/v1','actor-refinement-joint-panel/v1','conditions-presence-joint-panel/v1'")
a=replace_function(a,'scientific_acceptance',criterion_analyzer)
a=replace_function(a,'validate_capture',"""def validate_capture(raw,rows,greedy,joint,*,candidate=False,summary=None,report=None,state=None,latent='none',comparator='parent'):
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
""")
a=a.replace("len(plan['source_owner_pins'])==39","len(plan['source_owner_pins'])==40")
a=a.replace("len(summary['opening_owners'])==plan['expected_loaded_owner_count']==16","len(summary['opening_owners'])==plan['expected_loaded_owner_count']")
a=a.replace('source-bound16-loaded/39-owner','source-bound measured-loaded/40-owner-plus-supplement')
a=a.replace("(30,27,9)","(40,36,18)")
begin=a.index("    parent_contract=contract['completed_frozen_parent'];parent_review=")
end=a.index("    actual={};new_inference=0",begin)
a=a[:begin]+'''    comparator_inputs=read(contract['postfreeze_comparator_inputs']['path'],contract['postfreeze_comparator_inputs'])
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
''' +a[end:]
begin=a.index("    copied={}\n    for panel in (*PANELS,'training168'):")
end=a.index("    require(len(copied)==6",begin)
a=a[:begin]+'''    copied={}
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
''' +a[end:]
a=a.replace("(actual[s,panel] for s in STATES)","(actual[s,panel] for s in ('parent','initial','trained'))")
a=a.replace("len(summaries)==30 and len(scores)==27","len(summaries)==40 and len(scores)==36")
a=a.replace("'Exact30panels/27scores required'","'Exact40panels/36scores required'")
a=a.replace("paired={};parentpaired={};coupling={};ranks={}","paired={};parentpaired={};n11paired={};coupling={};ranks={}")
a=once(a,"        coupling[panel]=decoded_coupling(","        n11paired[panel]=paired_changes(scores['frozen_N11',panel],scores['trained',panel])\n        coupling[panel]=decoded_coupling(")
a=once(a,"    require(all(sum(r[view+'_exact_ir'] for r in scores['parent','training168'])==154 for view in ('raw','joint')),'Preregistered frozen N11 training154 baseline differs')",
 "    require(all(sum(r[view+'_exact_ir'] for r in scores[state,'training168'])==154\n        for state in ('parent','frozen_N11') for view in ('raw','joint')),'Both frozen training154 baselines required')")
a=a.replace("panel_count=30,authored_score_sets=27,paired_panel_count=9","panel_count=40,authored_score_sets=36,paired_panel_count=18")
a=a.replace("paired_frozen_parent_to_trained=parentpaired,scientific_acceptance=",
 "paired_frozen_parent_to_trained=parentpaired,paired_frozen_N11_to_trained=n11paired,scientific_acceptance=")
a=a.replace("new_parent_control_updates=0,new_parent_control_forwards=0,external_embedding_encoder_calls=0",
 "new_parent_control_updates=0,new_parent_control_forwards=0,new_N11_control_updates=0,new_N11_control_forwards=0,external_embedding_encoder_calls=0")
ap=F/'analyze_actor_context_ranking_v01.py';compile(a,str(ap),'exec')
with ap.open('x') as h:h.write(a)
print(json.dumps(dict(analyzer=pin(ap),recounter=tracepin,contract=contract,comparators=comparators,model=model)))

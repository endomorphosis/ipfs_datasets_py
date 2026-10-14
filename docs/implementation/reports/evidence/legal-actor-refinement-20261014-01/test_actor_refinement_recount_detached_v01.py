#!/usr/bin/env python3
"""Synthetic/source-AST F15 controls; no recounter main or result/reference reads."""
from pathlib import Path
import ast
import builtins
import copy
import hashlib
import json
import math
import re
import random
import struct
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'review_actor_refinement_result_recount_v01.py'
OLD=ROOT.parent/'legal-balanced-execution-20261014-01/review_conditions_balanced_result_recount_v01.py'
FIELDS=('actor','action','object','conditions','exceptions','temporal')
PANELS=('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law','fresh_dev','fresh_test')
SCOPES=tuple(panel for panel in (*PANELS,'training168') if panel!='law')
COUNTS=dict(zip(PANELS,(96,36,36,72,72,72,8,36,36)),training168=168)
STATES=('parent','initial','trained')


def deny(name,*args,**kwargs):raise AssertionError('No production/numerical import: '+name)


def selected(path,names,namespace):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=set(names) or len(nodes)!=len(names):raise AssertionError('Exact detached definitions required')
    if any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in nodes):raise AssertionError('No detached decorators/imports')
    namespace['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#synthetic-controls','exec'),namespace)
    return namespace


def namespace():
    raw=OLD.read_bytes()
    if len(raw)!=46595 or hashlib.sha256(raw).hexdigest()!='0c5b68645cc66e7758d1750c878f5be9fb117faad841fe27f73391c8ccbce8bf':raise AssertionError('Pinned immutable helper source differs')
    ns=dict(FIELDS=FIELDS,SCOPES=SCOPES,COUNTS=COUNTS,STATES=STATES,math=math,re=re,struct=struct,json=json,hashlib=hashlib,
        Path=Path,ast=ast,copy=copy,random=random,SimpleNamespace=SimpleNamespace,builtins=builtins,OBSERVED={})
    tree=ast.parse(SOURCE.read_bytes());module=ROOT/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    ns.update(TRAINER=module/'legal_span_actor_refinement.py',TARGETED=module/'legal_span_targeted_loss.py',SPLIT=module/'legal_span_split_features.py')
    ns['TRAINING_SOURCE_PINS']=(
        dict(path=str(ns['TRAINER']),bytes=56952,sha256='a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'),
        dict(path=str(ns['TARGETED']),bytes=49658,sha256='f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b'),
        dict(path=str(ns['SPLIT']),bytes=52067,sha256='886a0cde9924dceb5f5a4b655a995eb60a8f3fb954408d991fe4b4eb23ade0cd'))
    selected(SOURCE,('require','digest','f32','ranked','projection','initial_prediction_parity','independent_acceptance','permission_recount','recount_training','frozen_descriptor',
        'denied_import','detached_definitions','load_training_validators'),ns)
    def identity(path,pin):
        if str(path) not in {p['path'] for p in ns['TRAINING_SOURCE_PINS']}:raise AssertionError('Controls may read only three pinned sources')
        value=Path(path).read_bytes()
        if len(value)!=pin['bytes'] or hashlib.sha256(value).hexdigest()!=pin['sha256']:raise AssertionError('Pinned training source differs')
        return pin
    ns['identity']=identity
    selected(OLD,('coordinates','bits','choice','actor_coverage','coverage_summary','paired_score','presence_recount'),ns)
    names=('coordinates','bits','choice','actor_coverage','coverage_summary','paired_score','presence_recount')
    ns['load_helpers']=lambda:{name:ns[name] for name in names}
    validators=ns['load_training_validators']();ns['load_training_validators']=lambda:validators
    return ns


def fixture():
    contract=json.loads((ROOT/'evaluation-contract-v01.json').read_bytes())
    records={}
    for state in STATES:
        for panel in SCOPES:
            correct=154 if state=='parent' and panel=='training168' else 155 if panel=='training168' else COUNTS[panel]
            records[state,panel]=[dict(id=panel+'-'+str(i),**{route:dict(full_IR=i<correct) for route in ('raw','joint')}) for i in range(COUNTS[panel])]
    ids=['permission-'+str(i) for i in range(32)]
    permissions={state:dict(count=32,ids=list(ids),raw_P_to_P=32,joint_P_to_P=32,losses=0,abstentions=0) for state in STATES}
    return contract,records,permissions


def scores():
    return dict(tokens=[dict(text='actor',start=0,end=5),dict(text='acts',start=6,end=10)],modality_logits=[-0.,0.,1.],
        presence_logits={f:[0.,1.] for f in FIELDS[2:]},start_logits={f:[-0.,1.] for f in FIELDS},end_logits={f:[0.,1.] for f in FIELDS})


def training_fixture(ns):
    digest=ns['digest'];v=ns['load_training_validators']();owner=v['trainer'];target=v['targeted'];policy=owner['_policy']('actor-refinement-ce')
    training=[dict(id='synthetic-'+str(i),source_text='actor'+str(i)+' acts object',canonical_ir=dict(rules=[dict(modality='O',actor='actor'+str(i),action='acts',object='',conditions=[],exceptions=[],temporal=[])])) for i in range(168)]
    branches=('modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256','span_path_state_sha256',
        'dormant_latent_state_sha256','frozen_base34_state_sha256','actor_head_state_sha256','inactive_actor_head_rows_sha256',
        'actor_attention_query_sha256','actor_context_gate_sha256','conditions_presence_state_sha256','inactive_conditions_presence_rows_sha256','frozen_nonactor36_state_sha256')
    initial={name:digest(name) for name in branches};before=dict(initial);frozen=initial['frozen_nonactor36_state_sha256'];inactive=initial['inactive_actor_head_rows_sha256']
    cursor=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0);start=dict(cursor);batches=[];objectives=[];freezes=[];features=[]
    for step in range(1,33):
        indices=target['_batch_indices'](168,cursor,12,1729);after_progress=target['_advance_progress'](cursor,12,168)
        batch=target['_batch_trace_entry'](indices,training,cursor,after_progress,loss=1.25,gradient_norm=1.);batches.append(batch)
        join={key:batch[key] for key in ('optimizer_step','indices','ids')};rows=[];base_rows=[]
        for position,index in enumerate(indices):
            source=training[index];sha=hashlib.sha256(source['source_text'].encode()).hexdigest()
            rows.append(dict(id=source['id'],training_index=index,token_count=3,actor_gold_coordinates=[0,0],actor_present=True))
            base_rows.append(dict(token_count=3,padded_score_width=3,full_valid_boundary_span_count=6,compatible_wrong_candidate_count=1,
                compatible_wrong_domain_sha256=digest([(2,2)]),gold_coordinates=[0,0],gold_score_float32=0.,chosen_wrong_coordinates=[2,2],
                chosen_wrong_score_float32=0.,chosen_wrong_tie_count=1,present_gold_nonactor_coordinates=dict(action=[1,1]),argmax_detached=True,
                full_compatible_domain_traversed=True,padding_reversed_exactgold_and_othergold_overlap_excluded=True,
                selection_implementation='vectorized_detached_source_boundary_gather',row_position=position,id=source['id'],source_sha256=sha,
                actor_hinge_value=1.,hinge_active=True,gradient_enabled_by_policy=False,zero_domain_differentiable_zero=False,
                teacher_forced_compatibility=True,semantic_compatibility_verified=False))
        base=dict(schema='targeted-source-span-objective-diagnostics/v1',main_loss=1.25,actor_hinge_mean=1.,actor_hinge_applied=False,
            actor_hinge_coefficient=.25,total_loss=1.25,presence_CE_means=dict(conditions=.25,exceptions=.25),rows=base_rows,
            teacher_forcing=True,evaluation_references_used=False,semantic_compatibility_verified=False)
        objectives.append(dict(join,details=dict(base_objective=base,total_loss=1.25,batch_denominator=12,rows=rows,evaluation_references_used=False,teacher_forcing=True)))
        after=dict(before)
        for name in ('actor_head_state_sha256','actor_attention_query_sha256','actor_context_gate_sha256'):after[name]=digest([name,step])
        freezes.append(dict(join,source_frozen36_state_sha256=frozen,frozen_before=frozen,frozen_after=frozen,inactive_before=inactive,inactive_after=inactive,
            frozen_head_sample_sha256=digest(['heads',step]),frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,
            inactive_moments_zero=True,changed_parameter_names=list(owner['TRAINABLE_PARAMETER_NAMES']),completed_returned_update=True,
            branch_digests_before=before,branch_digests_after=after))
        feature=dict(join,gradients_finite_connected=True,trained_start_requirements_checked=step==1,fresh_zero_initialization_assumed=False)
        for name in ('query','gate','context','residual'):feature.update({name+'_gradient_l2':.25,name+'_gradient_exact_zero':False})
        for name,branch in (('query','actor_attention_query_sha256'),('gate','actor_context_gate_sha256')):
            feature.update({name+'_before_sha256':before[branch],name+'_after_sha256':after[branch],name+'_changed':True,
                name+'_Adam_moments_exact_zero':False,name+'_exp_avg_sha256':digest([name,'m',step]),name+'_exp_avg_sq_sha256':digest([name,'v',step])})
        features.append(feature);before=after;cursor=after_progress
    trace=lambda kind,values:dict(schema='completed-actor-refinement-adapter-'+kind+'-trace/v1',completed_updates=32,batches=values,batches_sha256=digest(values),independent_numerical_kernel_trace=False)
    objective=trace('objective',objectives);objective['evaluation_references_used']=False
    forward=dict(schema='actor-refinement-adapter-training-forward-accounting/v1',training_model_forward_calls=32,training_actor_features_model_calls=32,
        training_modality_encoder_calls=32,training_span_encoder_calls=64,training_conditions_presence_head_calls=32,
        actual_model_counter_deltas=dict.fromkeys(('source_model_forwards','actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'),32),
        training_source_row_occurrences=384,tuning_model_forward_calls=0,teacher_model_forward_calls=0,feature_paths_per_source_model_forward=3,restore_validation_and_external_evaluation_forwards_included=False)
    source='b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9'
    report=dict(schema='bounded-actor-refinement-adapter-training/v1',optimizer_steps=32,continuation_optimizer_steps_total=32,actor_training_count=168,
        training_executed=True,stopped_reason='step_limit',tuning=dict(rows_evaluated=0,used_for_fit_or_selection=False),source_conditions_presence_checkpoint_sha256='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd',
        source_conditions_presence_model_state_sha256=source,initial_model_state_sha256=source,training_call_initial_model_state_sha256=source,source_conditions_presence_optimizer_steps=32,
        training_policy=policy,training_policy_sha256=digest(policy),parameter_partition=owner['_partition'](),optimizer_parameter_order=list(owner['TRAINABLE_PARAMETER_NAMES']),
        stored_trainable_scalar_count=908,active_trainable_scalar_count=258,source_frozen36_state_sha256=frozen,inactive_head_rows_sha256_initial=inactive,inactive_head_rows_sha256_final=inactive,
        frozen_parent36_sha256_initial=frozen,frozen_parent36_sha256_final=frozen,frozen_parameters_sha256_initial=frozen,frozen_parameters_sha256_final=frozen,final_model_state_sha256=digest('synthetic final'),
        batch_trace=target['_trace_summary'](batches,start,cursor,policy['objective_policy'],training),batch_losses=[1.25]*32,objective_trace=objective,freeze_trace=trace('freeze',freezes),feature_trace=trace('feature',features),
        initial_branch_digests=initial,training_call_initial_branch_digests=initial,final_branch_digests=before,
        feature_learning=dict(query_changed_updates=32,gate_changed_updates=32,query_nonzero_gradient_updates=32,gate_nonzero_gradient_updates=32,context_nonzero_gradient_updates=32,residual_nonzero_gradient_updates=32),
        gradient_norm_max=1.,changed_parameter_names=list(owner['TRAINABLE_PARAMETER_NAMES']),forward_accounting=forward)
    schedule=dict(batch_indices=[b['indices'] for b in batches],batch_ids=[b['ids'] for b in batches],
        batch_indices_sha256=digest([b['indices'] for b in batches]),final_progress=cursor)
    return report,training,schedule


def reseal_traces(ns,report):
    for kind in ('objective','freeze','feature'):report[kind+'_trace']['batches_sha256']=ns['digest'](report[kind+'_trace']['batches'])


class Controls(unittest.TestCase):
    def setUp(self):self.ns=namespace()

    def test_actual_contract_pin(self):
        raw=(ROOT/'evaluation-contract-v01.json').read_bytes()
        self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(12913,'a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e'))

    def test_source_main_requires_training_hook_and_source_qualification(self):
        tree=ast.parse(SOURCE.read_bytes())
        flag=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TRAINING_TRACE_RECOUNT_CONFIGURED' for t in n.targets))
        self.assertIs(flag.value.value,True)
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        checks=[ast.unparse(n) for n in main.body[:4]]
        self.assertTrue(any('TRAINING_TRACE_RECOUNT_CONFIGURED is True' in value for value in checks))
        self.assertTrue(any(isinstance(n,ast.Constant) and n.value=='actor-refinement-result-recount-source-independent-review/v1' for n in ast.walk(main)))

    def test_criterion_passes_at_exact155_and_ignores_actor_ranks(self):
        c,r,p=fixture();r['trained','training168'][0]['actor_rank']=99999
        actual=self.ns['independent_acceptance'](c,r,p)
        self.assertTrue(actual['scientific_success']);self.assertEqual(actual['training168'],dict(raw_full_IR=155,joint_full_IR=155,minimum_required=155,passed=True))

    def test_each_training_view154_fails_scientifically(self):
        for route in ('raw','joint'):
            c,r,p=fixture();r['trained','training168'][154][route]['full_IR']=False
            result=self.ns['independent_acceptance'](c,r,p)
            self.assertFalse(result['scientific_success']);self.assertFalse(result['training168']['passed'])

    def test_no_scope_or_view_can_hide_completeIR_loss(self):
        for panel in SCOPES:
            for route in ('raw','joint'):
                c,r,p=fixture();r['trained',panel][0][route]['full_IR']=False
                if panel=='training168':r['trained',panel][155][route]['full_IR']=True
                result=self.ns['independent_acceptance'](c,r,p)
                self.assertFalse(result['scientific_success']);self.assertEqual(result['no_complete_IR_loss_IDs_vs_N11']['loss_ids_by_scope'][panel][route],[panel+'-0'])

    def test_permission_loss_and_abstention_remain_reportable(self):
        for key in ('losses','abstentions'):
            c,r,p=fixture();p['trained'][key]=1;p['trained']['joint_P_to_P']=31
            result=self.ns['independent_acceptance'](c,r,p)
            self.assertFalse(result['scientific_success']);self.assertEqual(result['all32_permission_retention'],dict(count=32,passed=False))

    def test_all_three_permission_states_are_checked(self):
        for state in STATES:
            c,r,p=fixture();p[state]['raw_P_to_P']=31
            self.assertFalse(self.ns['independent_acceptance'](c,r,p)['scientific_success'])

    def test_technical_failure_cannot_be_scientific_success(self):
        c,r,p=fixture();self.assertFalse(self.ns['independent_acceptance'](c,r,p,False)['scientific_success'])

    def test_missing_scope_duplicateID_boolean_count_refused(self):
        for mutate in (lambda r:r.pop(('initial','fresh_dev')),
            lambda r:r['initial','fresh_dev'][1].update(id=r['initial','fresh_dev'][0]['id']),
            lambda r:r['trained','fresh_dev'][0]['raw'].update(full_IR=1)):
            c,r,p=fixture();mutate(r)
            with self.assertRaises(ValueError):self.ns['independent_acceptance'](c,r,p)

    def test_changed_preregistered_threshold_refused(self):
        c,r,p=fixture();c['strict_scientific_success']['training168']['minimum_accepted_raw_and_joint']=154
        with self.assertRaises(ValueError):self.ns['independent_acceptance'](c,r,p)

    def test_final_projection_excludes_only_actor_vectors(self):
        a=scores();b=copy.deepcopy(a);b['start_logits']['actor'][0]=2.;b['end_logits']['actor'][1]=-2.
        project=self.ns['projection'];bits=self.ns['bits']
        self.assertEqual(bits(project(a,False)),bits(project(b,False)))
        self.assertNotEqual(bits(project(a)),bits(project(b)))
        self.assertEqual(set(project(a,False)['presence_logits']),set(FIELDS[2:]))
        self.assertEqual(set(project(a,False)['start_logits']),set(FIELDS[1:]))

    def test_all_protected_vectors_detect_changes(self):
        a=scores();baseline=self.ns['bits'](self.ns['projection'](a,False))
        for kind,roles in (('modality_logits',(None,)),('presence_logits',FIELDS[2:]),('start_logits',FIELDS[1:]),('end_logits',FIELDS[1:])):
            for role in roles:
                b=copy.deepcopy(a)
                if role is None:b[kind][0]=2.
                else:b[kind][role][0]=2.
                self.assertNotEqual(baseline,self.ns['bits'](self.ns['projection'](b,False)),(kind,role))

    def test_signed_zero_is_protected_binary32(self):
        a=scores();b=copy.deepcopy(a);b['modality_logits'][0]=0.
        self.assertNotEqual(self.ns['bits'](self.ns['projection'](a,False)),self.ns['bits'](self.ns['projection'](b,False)))

    def test_missing_protected_role_or_wrong_shape_refused(self):
        for mutate in (lambda s:s['presence_logits'].pop('conditions'),lambda s:s['end_logits'].pop('temporal'),lambda s:s['start_logits']['actor'].pop()):
            s=scores();mutate(s)
            with self.assertRaises(ValueError):self.ns['projection'](s,False)

    def test_nonbinary32_and_boolean_scores_refused(self):
        for value in (True,.1,float('nan'),float('inf')):
            s=scores();s['presence_logits']['conditions'][0]=value
            with self.assertRaises((ValueError,OverflowError)):self.ns['bits'](self.ns['projection'](s,False))

    def test_pinned_choice_guard_tie_and_class(self):
        self.assertIsNone(self.ns['choice']([0.,0.]));self.assertEqual(self.ns['choice']([0.,1.]),1)

    def test_actor_rank_can_change_in_pinned_helper(self):
        source=dict(id='synthetic',source_text='actor acts',canonical_ir=dict(rules=[dict(modality='F',actor='actor',action='acts',object='',conditions=[],exceptions=[],temporal=[])]))
        s=scores();s['modality_logits']=[0.,1.,2.]
        for f in FIELDS[2:]:s['presence_logits'][f]=[1.,0.]
        _,gold=self.ns['coordinates'](source);before=self.ns['actor_coverage'](source,s,gold)
        s['start_logits']['actor']=[4.,0.];s['end_logits']['actor']=[4.,0.]
        after=self.ns['actor_coverage'](source,s,gold)
        self.assertNotEqual(before['stable_rank'],after['stable_rank'])
        self.assertNotEqual(self.ns['coverage_summary']([before])['full_rank_records_sha256'],self.ns['coverage_summary']([after])['full_rank_records_sha256'])

    def test_pinned_pairing_reports_net_gain_with_a_loss(self):
        def row(identifier,correct):return dict(id=identifier,**{route:{metric:correct for metric in ('full_IR','modality',*FIELDS)} for route in ('raw','joint')})
        before=[row('a',True),row('b',False),row('c',False)];after=[row('a',False),row('b',True),row('c',True)]
        result=self.ns['paired_score'](before,after)['raw']['full_IR']
        self.assertEqual((result['gains'],result['losses'],result['loss_ids']),(2,1,['a']))

    def test_permission_recount_does_not_refuse_candidate_failure(self):
        ir=dict(rules=[dict(modality='P')]);sources=[dict(id='p'+str(i),canonical_ir=ir) for i in range(32)]
        greedy=[dict(status='decoded',canonical_ir=copy.deepcopy(ir)) for _ in sources]
        chosen=[dict(result=dict(status='selected',canonical_ir=copy.deepcopy(ir))) for _ in sources]
        greedy[0]['canonical_ir']['rules'][0]['modality']='O';chosen[1]['result']=dict(status='ambiguous',canonical_ir=None)
        result=self.ns['permission_recount'](sources,dict(inference=dict(rows=greedy)),chosen)
        self.assertEqual((result['count'],result['raw_P_to_P'],result['joint_P_to_P'],result['losses'],result['abstentions']),(32,31,31,1,1))

    def test_unfrozen_descriptor_refused(self):
        pin=dict(path='/synthetic/raw.json',bytes=5,sha256='a'*64);freeze=dict(results={pin['path']:{k:pin[k] for k in ('bytes','sha256')}})
        self.assertEqual(self.ns['frozen_descriptor'](pin,freeze),pin)
        for key,value in (('path','/synthetic/other.json'),('sha256','b'*64)):
            bad=dict(pin);bad[key]=value
            with self.assertRaises(ValueError):self.ns['frozen_descriptor'](bad,freeze)

    def test_real_trace_schema_accepts32_nonzero_first_query_moments(self):
        report,training,schedule=training_fixture(self.ns)
        result=self.ns['recount_training'](report,training,schedule)
        self.assertEqual((result['updates'],result['source_occurrences']),(32,384))
        self.assertEqual(result['feature_learning']['query_changed_updates'],32)
        self.assertFalse(result['independent_numerical_gradient_proof']);self.assertFalse(result['scalar_CE_recomputed'])

    def test_training_partition_frozen_conditions_and_return_limit_refused(self):
        mutations=(lambda r:r.update(optimizer_steps=31),lambda r:r.update(stopped_reason='deadline_before_batch'),
            lambda r:r['tuning'].update(rows_evaluated=1),lambda r:r['parameter_partition']['frozen_parameter_names'].remove('conditions_presence.bias'),
            lambda r:r['optimizer_parameter_order'].append('conditions_presence.weight'),lambda r:r.update(frozen_parent36_sha256_final='f'*64),
            lambda r:r['forward_accounting'].update(training_source_row_occurrences=383))
        for mutate in mutations:
            report,training,schedule=training_fixture(self.ns);mutate(report)
            with self.assertRaises(ValueError):self.ns['recount_training'](report,training,schedule)

    def test_changed_conditions_and_inactive_moments_cannot_hide_behind_new_trace_digest(self):
        mutations=(lambda r:r['freeze_trace']['batches'][7]['branch_digests_after'].update(conditions_presence_state_sha256='f'*64),
            lambda r:r['freeze_trace']['batches'][7].update(inactive_moments_zero=False),
            lambda r:r['freeze_trace']['batches'][7].update(frozen_gradients_none=False),
            lambda r:r['freeze_trace']['batches'][7].update(changed_parameter_names=['conditions_presence.bias']))
        for mutate in mutations:
            report,training,schedule=training_fixture(self.ns);mutate(report);reseal_traces(self.ns,report)
            with self.assertRaises(ValueError):self.ns['recount_training'](report,training,schedule)

    def test_feature_digest_and_training_branch_chain_must_join(self):
        for mutate in (lambda r:r['feature_trace']['batches'][5].update(query_before_sha256='f'*64),
            lambda r:r['freeze_trace']['batches'][5].update(branch_digests_before=dict(r['freeze_trace']['batches'][5]['branch_digests_before'],actor_head_state_sha256='f'*64)),
            lambda r:r['feature_trace']['batches'][0].update(fresh_zero_initialization_assumed=True)):
            report,training,schedule=training_fixture(self.ns);mutate(report);reseal_traces(self.ns,report)
            with self.assertRaises(ValueError):self.ns['recount_training'](report,training,schedule)

    def test_actual_sourceSHA_authentication_exceeds_owner_validator(self):
        report,training,schedule=training_fixture(self.ns)
        objective=report['objective_trace']['batches'][4];objective['details']['base_objective']['rows'][0]['source_sha256']='f'*64
        self.ns['load_training_validators']()['trainer']['_validate_objective_entry'](objective,report['batch_trace']['batches'][4],report['training_policy'])
        reseal_traces(self.ns,report)
        with self.assertRaisesRegex(ValueError,'source/gold actor'):self.ns['recount_training'](report,training,schedule)

    def test_actual_gold_coordinates_authentication_exceeds_owner_validator(self):
        report,training,schedule=training_fixture(self.ns);objective=report['objective_trace']['batches'][4]
        objective['details']['rows'][0]['actor_gold_coordinates']=[2,2]
        row=objective['details']['base_objective']['rows'][0]
        row.update(gold_coordinates=[2,2],chosen_wrong_coordinates=[0,0],compatible_wrong_domain_sha256=self.ns['digest']([(0,0)]))
        self.ns['load_training_validators']()['trainer']['_validate_objective_entry'](objective,report['batch_trace']['batches'][4],report['training_policy'])
        reseal_traces(self.ns,report)
        with self.assertRaisesRegex(ValueError,'source/gold actor'):self.ns['recount_training'](report,training,schedule)

    def test_reported_schedule_digest_and_feature_learning_counters_checked(self):
        for mutate in (lambda r,s:s['batch_indices'][0].reverse(),lambda r,s:r['feature_learning'].update(query_nonzero_gradient_updates=31),
            lambda r,s:r['objective_trace'].update(batches_sha256='f'*64),lambda r,s:r['batch_losses'].__setitem__(0,2.)):
            report,training,schedule=training_fixture(self.ns);mutate(report,schedule)
            with self.assertRaises(ValueError):self.ns['recount_training'](report,training,schedule)

    def test_closed_schedule_hash_and_final_progress_are_authenticated(self):
        for mutate in (lambda s:s.update(extra=True),lambda s:s.pop('batch_indices_sha256'),
            lambda s:s.update(batch_indices_sha256='f'*64),lambda s:s.update(final_progress=dict(epochs_completed=2,row_cursor=36,optimizer_steps=31))):
            report,training,schedule=training_fixture(self.ns);mutate(schedule)
            with self.assertRaisesRegex(ValueError,'four-field prepared schedule'):self.ns['recount_training'](report,training,schedule)

    def test_complete_initial_greedy_fields_and_joint_envelope_protected(self):
        greedy=[dict(status='decoded',reason=None,canonical_ir=dict(rules=[]),span_diagnostics=dict(actor=[0,0]),minimum_decision_logit_margin=1.)]
        joint=[dict(id='synthetic',result=dict(status='selected',canonical_ir=dict(rules=[])),candidate_count=8)]
        self.ns['initial_prediction_parity'](greedy,copy.deepcopy(greedy),joint,copy.deepcopy(joint))
        for key,value in (('status','ambiguous'),('reason','changed'),('canonical_ir',None),('span_diagnostics',{}),('minimum_decision_logit_margin',2.)):
            altered=copy.deepcopy(greedy);altered[0][key]=value
            with self.assertRaisesRegex(ValueError,'complete saved greedy'):self.ns['initial_prediction_parity'](greedy,altered,joint,joint)
        for mutate in (lambda rows:rows[0].update(candidate_count=9),lambda rows:rows[0].update(id='other'),
            lambda rows:rows[0]['result'].update(reason='changed')):
            altered=copy.deepcopy(joint);mutate(altered)
            with self.assertRaisesRegex(ValueError,'complete saved joint envelope'):self.ns['initial_prediction_parity'](greedy,greedy,joint,altered)


if __name__=='__main__':unittest.main()

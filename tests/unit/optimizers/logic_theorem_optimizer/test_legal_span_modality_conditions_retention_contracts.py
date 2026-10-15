"""Detached stdlib/fake contracts. No production or numerical package import."""
import ast
import builtins
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import re
import struct
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parents[4]/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_modality_conditions_retention.py'
FIELDS=('actor','action','object','conditions','exceptions','temporal')
OPTIONAL=FIELDS[2:]


def require(value,message):
    if not value:raise ValueError(message)


def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def digest(value):return hashlib.sha256(raw(value)).hexdigest()

def deny(name,*args,**kwargs):raise AssertionError('Production/numerical import forbidden: '+name)


def namespace():
    oldtest=Path(__file__).with_name('test_legal_span_joint_readout_retention_contracts.py')
    selected=[node for node in ast.parse(oldtest.read_bytes()).body if isinstance(node,ast.FunctionDef)
        and node.name in {'require','raw','digest','deny','namespace'}]
    env=dict(ast=ast,builtins=builtins,copy=copy,hashlib=hashlib,json=json,math=math,Path=Path,random=random,re=re,struct=struct,
        SimpleNamespace=SimpleNamespace,__file__=str(oldtest),SOURCE=SOURCE.with_name('legal_span_joint_readout_retention.py'))
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(oldtest)+'#detached-dependencies','exec'),env)
    joint=env['namespace']()
    capture_source=SOURCE.parents[2]/'logic/formalization/autoencoder/retained_span_score_capture.py'
    cn=dict(json=json,hashlib=hashlib,math=math,struct=struct,SPAN_FIELDS=FIELDS,OPTIONAL_FIELDS=OPTIONAL,MODALITIES=('O','P','F'),
        __file__=str(capture_source),__builtins__=dict(vars(builtins),__import__=deny))
    names={'_require','_wire','_same','_f32','_pair_winners','_verify_greedy'}
    functions=[node for node in ast.parse(capture_source.read_bytes()).body if isinstance(node,ast.FunctionDef) and node.name in names]
    require({node.name for node in functions}==names,'Exact real greedy verifier slice required')
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(capture_source)+'#pure-greedy','exec'),cn)
    n={key:joint[key] for key in ('copy','hashlib','json','math','Path','features','conditions','refinement','ranking','targeted','continuation','span')}
    n.update(__file__=str(SOURCE),joint=SimpleNamespace(**joint),capture=SimpleNamespace(**cn),__builtins__=dict(vars(builtins),__import__=deny))
    nodes=[node for node in ast.parse(SOURCE.read_bytes()).body if isinstance(node,(ast.Assign,ast.FunctionDef,ast.ClassDef))]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#detached-model-contracts','exec'),n)
    n['joint_namespace']=joint
    n['span'].tokenize_source=lambda text:[dict(text=m.group(),start=m.start(),end=m.end(),byte_ids=[b+1 for b in m.group().encode()]) for m in re.finditer(r'\w+|[^\w\s]',text)]
    n['span'].codec_module=SimpleNamespace(_rule=lambda value:copy.deepcopy(value['rules'][0]))
    return n


def row_fixture(n,index=0,*,wrong_conditions=True,wrong_modality=False,tied=False):
    text='Actor acts object when unless later';tokens=[{key:t[key] for key in ('text','start','end')} for t in n['span'].tokenize_source(text)]
    ident=('synthetic-condition_exception_duration-' if index<2 else 'synthetic-training-')+str(index)
    gold=dict(modality='O',actor='Actor',action='acts',object='object',conditions=['when'],exceptions=[],temporal=[])
    labels=dict(modality=0,presence=[True,True,True,True,False,False],spans=[(0,0),(1,1),(2,2),(3,3),(-100,-100),(-100,-100)])
    example=dict(id=ident,source_text=text,canonical_ir=dict(rules=[gold]),fixture_labels=labels)
    record=dict(id=ident,source_text=text,tokens=n['span'].tokenize_source(text),labels=copy.deepcopy(labels))
    scores=dict(schema='joint-source-span-scores/v1',tokens=tokens,modality_logits=[0.,0.,0.] if tied else ([0.,3.,0.] if wrong_modality else [3.,0.,0.]),
        presence_logits={role:([0.,4.] if role in ('object','conditions') else [4.,0.]) for role in OPTIONAL},start_logits={},end_logits={})
    positions=dict(actor=0,action=1,object=2,conditions=4 if wrong_conditions else 3,exceptions=0,temporal=0)
    for role in FIELDS:
        scores['start_logits'][role]=[4. if i==positions[role] else 0. for i in range(6)]
        scores['end_logits'][role]=list(scores['start_logits'][role])
    predicted=copy.deepcopy(gold);predicted['modality']='P' if wrong_modality else 'O';predicted['conditions']=['unless'] if wrong_conditions else ['when']
    facets={}
    if not tied:
        for role in FIELDS:
            present=role not in ('exceptions','temporal');position=positions[role]
            t=tokens[position]
            facets[role]=dict(present=present,presence_logit_margin=4. if role in OPTIONAL else None,
                token_start=position if present else None,token_end_inclusive=position if present else None,
                char_start=t['start'] if present else None,char_end=t['end'] if present else None,text=t['text'] if present else None,
                span_logit_margin=4. if present else None)
    observed=dict(source_sha256=hashlib.sha256(text.encode()).hexdigest(),status='abstained' if tied else 'decoded',
        reason='ambiguous_decoder_scores' if tied else None,canonical_ir=None if tied else dict(rules=[predicted]),
        minimum_decision_logit_margin=0. if tied else 3.,span_diagnostics=dict(tokens=tokens,facets=facets,modality_logits=scores['modality_logits']))
    occurrence=dict(id=ident,source_sha256=observed['source_sha256'],scores=scores)
    return example,record,occurrence,observed


def fixture(n):
    joint=n['joint_namespace'];state={name:[float(i)] for i,name in enumerate(n['MODEL_PARAMETER_NAMES'])}
    for name,shape in joint['_trainable_shapes']().items():state[name]=[[.25]*shape[1] for _ in range(shape[0])] if len(shape)==2 else [.25]*shape[0]
    for name in ('conditions_presence.weight','conditions_presence.bias'):state[name]=[[.375]*64 for _ in range(8)] if name.endswith('weight') else [.375]*8
    rows=[];occurrences=[];observed=[]
    for index in range(168):
        example,record,occurrence,row=row_fixture(n,index,wrong_conditions=index<2)
        rows.append(example);occurrences.append(occurrence);observed.append(row)
    def bounded(examples,tuning):
        require(len(examples)==168 and not tuning,'Training168 only')
        return [dict(id=e['id'],source_text=e['source_text'],tokens=n['span'].tokenize_source(e['source_text']),labels=copy.deepcopy(e['fixture_labels'])) for e in examples],[]
    n['targeted']._bounded_splits=bounded
    contract=dict(mode='source-only',dimension=384);child=dict(context_contract=contract,context_contract_sha256=digest(contract))
    parent=dict(model_state=state,progress=dict(optimizer_steps=32),training_manifest_sha256=digest(rows),
        config=dict(hidden_size=32,latent_dimension=384,latent_enabled=False),initial_continuation_checkpoint=child,
        source_parent_checkpoint_sha256='a'*64,source_parent_model_state_sha256='b'*64)
    legacy=joint['old_namespace'];parent['source_frozen36_state_sha256']=digest({key:state[key] for key in legacy['BASE_PARAMETER_NAMES']})
    for table in (n,joint,legacy):
        table['SOURCE_ACTOR_REFINEMENT_SHA256']=digest(parent);table['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256']=digest(state)
    legacy['SOURCE_FROZEN36_SHA256']=parent['source_frozen36_state_sha256']
    capture=dict(schema='actor-refinement-adapter-target-free-head-capture/v1',
        inference=dict(checkpoint_sha256=digest(parent),model_state_sha256=digest(state),target_access=False,teacher_forcing=False,rows=observed),
        target_access=False,teacher_forcing=False,extra_capture_forwards=0,actual_source_forwards=168,occurrences=occurrences)
    text=raw(capture)
    for table in (n,joint):table['TEACHER_CAPTURE_BYTES']=len(text);table['TEACHER_CAPTURE_SHA256']=hashlib.sha256(text).hexdigest()
    targets=n['_training_targets'](text,rows,digest(rows));certificate=dict(schema='modality-conditions-training-mask/v1',passed=True,findings=[],
        targets=n['_mask_certificate_targets'](targets['teacher_training'],targets['row_weight_training']))
    cp=n['build_checkpoint'](parent,rows,context_contract=contract,teacher_training_capture=text,training_mask_certificate=certificate)
    return parent,rows,text,certificate,cp


class Vector:
    def __init__(self,values):self.values=list(values)
    def mean(self):return math.fsum(self.values)/len(self.values)
    def __mul__(self,other):
        values=other.values if isinstance(other,Vector) else [other]*len(self.values)
        return Vector(a*b for a,b in zip(self.values,values,strict=True))


class Contracts(unittest.TestCase):
    def setUp(self):self.n=namespace()

    def test_closed_F15_six_tensor_policy_geometry_and_no_hinge(self):
        n=self.n;policy=n['_policy']('modality-conditions-retention-ce');n['_validate_policy'](policy)
        self.assertEqual(n['SOURCE_ACTOR_REFINEMENT_SHA256'],'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
        self.assertEqual(n['TRAINABLE_PARAMETER_NAMES'],('modality.weight','modality.bias','start.weight','start.bias','end.weight','end.bias'))
        part=policy['parameter_partition'];self.assertEqual((part['model_tensor_count'],part['trainable_tensor_count'],part['frozen_tensor_count']),(42,6,36))
        self.assertEqual((part['stored_trainable_scalar_count'],part['active_trainable_scalar_count'],part['inactive_stored_scalar_count']),(975,325,650))
        self.assertEqual(sum(math.prod(shape) for shape in n['_trainable_shapes']().values()),975)
        self.assertFalse(policy['objective_policy']['actor_ranking_enabled']);self.assertTrue(policy['actor_hinge_omitted'])
        self.assertTrue(policy['parent_ablation_only']);self.assertFalse(policy['strict_global_win_expected'])
        self.assertEqual(policy['retention']['blocks'],['actor_start','actor_end','modality','conditions_start','conditions_end','exceptions_presence'])
        for mutate in (lambda p:p['retention'].update(coefficient=0.),lambda p:p['conditions_row_weight'].update(selected=3),
            lambda p:p['parameter_partition']['active_rows'].update({'start.bias':[0]}),lambda p:p.update(actor_hinge_applied=True)):
            bad=copy.deepcopy(policy);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_policy'](bad)

    def test_entire_facet_weights_zero_one_two_rows_fullB_and_presence_constant(self):
        n=self.n;facets=[Vector([float(i+1),float(i+2)]) for i in range(6)];modality=1.25
        legacy=(2*modality+sum(vector.mean() for vector in facets))/8
        for values in ([1.,1.],[2.,1.],[2.,2.]):
            weighted,unweighted=n['_weighted_main_loss'](modality,facets,Vector(values))
            expected=(2*modality+sum(vector.mean() for i,vector in enumerate(facets) if i!=3)
                +sum(v*w for v,w in zip(facets[3].values,values))/2)/8
            self.assertEqual(unweighted,legacy);self.assertEqual(weighted,expected)
        # Whole optional facet includes its frozen presence CE: (2presence+1pointer)*2=6, not2+2=4.
        rows=[Vector([0.,0.]) for _ in range(6)];rows[3]=Vector([3.,3.])
        self.assertEqual(n['_weighted_main_loss'](0.,rows,Vector([2.,2.]))[0],6/8)
        duplicated=[Vector(v.values*2) for v in facets]
        self.assertEqual(n['_weighted_main_loss'](modality,facets,Vector([2.,1.])),n['_weighted_main_loss'](modality,duplicated,Vector([2.,1.,2.,1.])))

    def test_real_greedy_replay_mask_separate_from_component_KL_and_abstention(self):
        n=self.n;e,record,occurrence,observed=row_fixture(n)
        row=n['_weight_row'](occurrence,observed,record,e,0)
        self.assertEqual(row['error_fields'],['conditions']);self.assertTrue(row['conditions_only_mask']);self.assertEqual(row['conditions_facet_weight'],2)
        for mode in ('modality_coerror','tie','correct'):
            e,record,occurrence,observed=row_fixture(n,wrong_conditions=mode!='correct',wrong_modality=mode=='modality_coerror',tied=mode=='tie')
            row=n['_weight_row'](occurrence,observed,record,e,0)
            self.assertFalse(row['conditions_only_mask']);self.assertEqual(row['conditions_facet_weight'],1)
            if mode=='tie':self.assertEqual(row['error_fields'],list(n['ERROR_FIELDS']))
        bad=copy.deepcopy(observed);bad['span_diagnostics']['facets']['conditions']['text']='forged'
        with self.assertRaises(ValueError):n['_weight_row'](occurrence,bad,record,e,0)

    def test_full168_mask_certificate_and_every_batch_roots(self):
        n=self.n;parent,examples,text,certificate,cp=fixture(n);n['_validated'](cp)
        weights=cp['row_weight_training'];teacher=cp['teacher_training']
        self.assertEqual(weights['selected_ids'],[examples[0]['id'],examples[1]['id']]);self.assertEqual(weights['selected_count'],2)
        self.assertFalse(teacher['rows'][0]['blocks']['conditions_start']['mask']);self.assertFalse(teacher['rows'][0]['blocks']['conditions_end']['mask'])
        self.assertTrue(teacher['rows'][0]['blocks']['modality']['mask'])
        n['_validate_training_mask_certificate'](certificate,teacher,weights)
        records=n['_training_records'](examples);selected=n['_weight_batch']([records[i] for i in [1,2]],[1,2],weights)
        self.assertEqual([row['conditions_facet_weight'] for row in selected],[2,1])
        for indices in ([True,2],[1.,2],[2,1]):
            with self.subTest(indices=indices),self.assertRaises(ValueError):n['_weight_batch']([records[1],records[2]],indices,weights)

    def test_recomputed_mask_teacher_and_certificate_hashes_cannot_forge_targets(self):
        n=self.n;_,_,_,_,cp=fixture(n)
        for mode in ('weight','reorder','KLmask','gold','teacher_text','certificate'):
            bad=copy.deepcopy(cp)
            if mode=='weight':bad['row_weight_training']['rows'][0].update(conditions_only_mask=False,conditions_facet_weight=1,error_fields=[])
            elif mode=='reorder':bad['row_weight_training']['rows'][0],bad['row_weight_training']['rows'][1]=bad['row_weight_training']['rows'][1],bad['row_weight_training']['rows'][0]
            elif mode=='KLmask':bad['teacher_training']['rows'][0]['blocks']['conditions_start']['mask']=True
            elif mode=='gold':bad['teacher_training_examples'][0]['fixture_labels']['modality']=2
            elif mode=='teacher_text':bad['teacher_capture_utf8']+=' '
            else:bad['training_mask_certificate']['targets']['selected_ids'].reverse()
            bad['row_weight_training']['rows_sha256']=digest(bad['row_weight_training']['rows']);bad['row_weight_training_sha256']=digest(bad['row_weight_training'])
            bad['teacher_training']['rows_sha256']=digest(bad['teacher_training']['rows']);bad['teacher_training_sha256']=digest(bad['teacher_training'])
            bad['training_mask_certificate_sha256']=digest(bad['training_mask_certificate']);bad['initial_checkpoint_sha256']=digest(n['_origin'](bad))
            with self.subTest(mode=mode),self.assertRaises(ValueError):n['_validated'](bad)

    def test_full_copy_six_grad_selection_and_650_Adam_rows(self):
        n=self.n;parent,_,_,_,cp=fixture(n)
        self.assertEqual(cp['model_state'],parent['model_state']);self.assertIsNot(cp['model_state'],parent['model_state']);self.assertEqual(cp['optimizer_state']['parameters'],{})
        self.assertEqual(sum(len(value)*(64 if name.endswith('weight') else 1) for name,value in n['_inactive_state'](cp['model_state']).items()),650)
        class Parameter:
            def __init__(self,shape,address):self.shape=shape;self.address=address;self.grad='stale'
            def numel(self):return math.prod(self.shape)
            def requires_grad_(self,enabled):self.enabled=enabled
            def untyped_storage(self):return self
            def data_ptr(self):return self.address
        values={name:Parameter(n['_trainable_shapes']().get(name,(1,)),i) for i,name in enumerate(n['MODEL_PARAMETER_NAMES'])}
        model=SimpleNamespace(named_parameters=lambda:list(values.items()));_,selected=n['_configure_parameters'](model)
        self.assertEqual(selected,[values[name] for name in n['TRAINABLE_PARAMETER_NAMES']]);self.assertEqual(sum(value.enabled for value in values.values()),6)
        self.assertTrue(all(value.grad is None for value in values.values()))
        moments=dict(schema='adam-default-betas-eps/v1',parameters={})
        for name,shape in n['_trainable_shapes']().items():
            zero=[[0.]*shape[1] for _ in range(shape[0])] if len(shape)==2 else [0.]*shape[0]
            moments['parameters'][name]=dict(step=1,exp_avg=copy.deepcopy(zero),exp_avg_sq=copy.deepcopy(zero))
        n['_validate_optimizer_state'](moments,1)
        bad=copy.deepcopy(moments);bad['parameters']['start.bias']['exp_avg'][0]=1.
        with self.assertRaises(ValueError):n['_validate_optimizer_state'](bad,1)
        for value in (True,float('nan'),float('inf')):
            bad=copy.deepcopy(cp);bad['model_state']['modality.bias'][0]=value
            with self.assertRaises(ValueError):n['_validated'](bad)
        values['start.bias'].address=values['modality.bias'].address
        with self.assertRaises(ValueError):n['_configure_parameters'](model)

    def test_no_candidate_or_eval_membership_can_enter_frozen_training_mask(self):
        n=self.n;_,rows,text,certificate,cp=fixture(n)
        with self.assertRaises(ValueError):n['_training_targets'](text,rows[::-1],digest(rows))
        bad=copy.deepcopy(rows);bad[0]['id']='targeted-loss-authored_eval-forbidden'
        with self.assertRaises(ValueError):n['_training_targets'](text,bad,digest(rows))
        for key in ('source_sha256','tokens_sha256','labels_sha256'):
            bad=copy.deepcopy(cp['row_weight_training']);bad['rows'][0][key]='0'*64;bad['rows_sha256']=digest(bad['rows'])
            with self.subTest(key=key),self.assertRaises(ValueError):n['_weight_batch'](n['_training_records'](rows)[:1],[0],bad)

    def test_stable_KL_math_unchanged_six_blocks_wrong_and_absent_masks(self):
        n=self.n;_,_,_,_,cp=fixture(n)
        self.assertEqual(n['_log_softmax']([1e20,1e20]),[-math.log(2)]*2)
        self.assertEqual(n['_log_softmax']([-1e20,-1e20]),[-math.log(2)]*2)
        self.assertEqual(n['_kl_reference']([1e20,1e20],[-1e20,-1e20]),0.)
        teacher=cp['teacher_training']['rows'][0]
        self.assertFalse(teacher['blocks']['conditions_start']['mask']);self.assertFalse(teacher['blocks']['conditions_end']['mask'])
        self.assertEqual(teacher['blocks']['exceptions_presence']['gold_index'],0)
        self.assertTrue(teacher['blocks']['exceptions_presence']['mask'])
        _,record,occurrence,_=row_fixture(n)
        record['labels']['presence'][3]=False;record['labels']['spans'][3]=(-100,-100)
        absent=n['_teacher_row'](occurrence,record,0)
        self.assertIsNone(absent['blocks']['conditions_start']['gold_index'])
        self.assertIsNone(absent['blocks']['conditions_end']['gold_index'])
        self.assertFalse(absent['blocks']['conditions_start']['mask']);self.assertFalse(absent['blocks']['conditions_end']['mask'])
        policy=n['_policy']('modality-conditions-retention-ce')
        self.assertEqual(policy['retention']['normalization'],'sum_masked_row_block_KL_divide_6_times_full_batch_including_masked_frozen_zeros')
        self.assertTrue(policy['retention']['wrong_teacher_blocks_masked_out']);self.assertTrue(policy['retention']['row_weight_mask_is_separate'])

    def test_weighted_trace_replays_fullB_association_and_refuses_forged_products(self):
        n=self.n;_,_,_,_,cp=fixture(n);weights=cp['row_weight_training'];rows=[]
        for index in (0,2):
            target=weights['rows'][index];facet=[1.,2.,3.,4.,5.,6.]
            rows.append(dict(id=target['id'],training_index=index,source_sha256=target['source_sha256'],
                weight_target_sha256=digest(target),conditions_facet_weight=target['conditions_facet_weight'],modality_CE=1.,facet_CEs=facet,
                conditions_presence_CE=2.,conditions_start_CE=1.,conditions_end_CE=3.,
                weighted_conditions_facet_CE=float(4*target['conditions_facet_weight'])))
        means=[1.,2.,3.,4.,5.,6.];weighted=[1.,2.,3.,6.,5.,6.]
        ce=dict(schema='modality-conditions-entire-facet-weighted-CE/v1',rows=rows,batch_denominator=2,outer_denominator=8,
            modality_multiplier=2,modality_CE_mean=1.,facet_CE_means=means,weighted_facet_CE_means=weighted,
            weighted_main_loss=3.125,unweighted_main_loss=2.875,row_weight_rows_sha256=weights['rows_sha256'],
            near_complete_mask_sha256=weights['near_complete_mask_sha256'],actor_hinge_applied=False,actor_hinge_omitted=True,
            teacher_forcing=True,evaluation_references_used=False)
        batch=dict(indices=[0,2],ids=[row['id'] for row in rows]);n['_validate_CE_entry'](ce,batch,weights)
        for mode in ('pointer_only','sumweights','outer','id','source','target','weight','nonconditions','hinge','bool_index'):
            bad=copy.deepcopy(ce);actual=copy.deepcopy(batch)
            if mode=='pointer_only':bad['rows'][0]['weighted_conditions_facet_CE']=6.
            elif mode=='sumweights':bad['weighted_facet_CE_means'][3]=4.
            elif mode=='outer':bad['outer_denominator']=6
            elif mode=='id':bad['rows'][0]['id']='evaluation-forbidden'
            elif mode=='source':bad['rows'][0]['source_sha256']='0'*64
            elif mode=='target':bad['rows'][0]['weight_target_sha256']='0'*64
            elif mode=='weight':bad['rows'][0]['conditions_facet_weight']=1
            elif mode=='nonconditions':bad['weighted_facet_CE_means'][0]=2.
            elif mode=='hinge':bad['actor_hinge_applied']=True
            else:actual['indices'][0]=False
            with self.subTest(mode=mode),self.assertRaises(ValueError):n['_validate_CE_entry'](bad,actual,weights)

if __name__=='__main__':unittest.main(verbosity=2)

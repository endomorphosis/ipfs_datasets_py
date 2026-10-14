"""Detached stdlib continuation contracts; no production/numerical imports or weights."""
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

SOURCE=Path(__file__).resolve().parents[4]/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_context_ranking.py'

def require(value,message):
    if not value:raise ValueError(message)
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def digest(value):return hashlib.sha256(raw(value)).hexdigest()
def deny(name,*args,**kwargs):raise AssertionError('detached control refuses import: '+name)
def selected(path,names,ns):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in nodes}==set(names),'exact selected definitions')
    require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'detached imports refused')
    ns['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#detached','exec'),ns)
    return ns

def namespace():
    split_path=SOURCE.with_name('legal_span_split_features.py');split_ns=dict(checkpoint_digest=digest,_require=require)
    wanted={'FACET_PARAMETER_NAMES','ORIGINAL_PARAMETER_NAMES','FEATURE_PARAMETER_NAMES','SPLIT_FEATURE_PARAMETER_NAMES','LATENT_PARAMETER_NAMES','MODEL_PARAMETER_NAMES'}
    for n in ast.parse(split_path.read_bytes()).body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in wanted for t in n.targets):
            exec(compile(ast.Module(body=[n],type_ignores=[]),'#constants','exec'),split_ns)
    selected(split_path,{'_branch_digests'},split_ns)
    base=split_ns['MODEL_PARAMETER_NAMES'];head=('actor_start.weight','actor_start.bias','actor_end.weight','actor_end.bias');vectors=('actor_attention.query','actor_context.gate')
    span=SimpleNamespace(FALSE=dict.fromkeys(('admitted','formalized','promotion_performed','proof_authority','publication_performed','qualified','roundtrip_ok','semantic_correctness_verified'),False),
        _require=require,_raw=raw,checkpoint_digest=digest,_SHA=re.compile(r'[0-9a-f]{64}\Z'),SPAN_FIELDS=('actor','action','object','conditions','exceptions','temporal'),
        OPTIONAL_FIELDS=('object','conditions','exceptions','temporal'),_implementation=lambda:dict(inert='span'))
    span.tokenize_source=lambda text:[dict(text=t) for t in text.split()]
    target_ns=dict(copy=copy,hashlib=hashlib,json=json,math=math,random=random,struct=struct,span=span,SPAN_FIELDS=span.SPAN_FIELDS,
        MAX_SOURCE_TOKENS=128,MAX_NEW_STEPS=32,MAX_SECONDS=32,POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995')
    target_names={'_require','_raw','checkpoint_digest','_policy','_validate_policy','_combine_total_loss','_f32','_span_coordinates','_actor_domain','_actor_record','_choose_actor_wrong','_actor_auxiliary','_validate_objective_diagnostics','_progress','_batch_indices','_advance_progress'}
    selected(SOURCE.with_name('legal_span_targeted_loss.py'),target_names,target_ns)
    def bounded(rows,tuning):
        require(len(rows)==168 and not tuning,'training-only168')
        return [dict(id=r['id'],source_text=r['source_text'],tokens=[dict(text=t) for t in r['source_text'].split()],labels=dict(modality=0,presence=[True,True,False,False,False,False],spans=[(0,0),(1,1),(-100,-100),(-100,-100),(-100,-100),(-100,-100)])) for r in rows],[]
    targeted=SimpleNamespace(MAX_BYTES=128*1024*1024,LEGACY96_SHA256=target_ns['LEGACY96_SHA256'],_implementation=lambda:dict(inert='targeted'),_bounded_splits=bounded,**{k:target_ns[k] for k in target_names})
    old=dict(copy=copy,math=math,BASE_PARAMETER_NAMES=base,MODEL_PARAMETER_NAMES=base+head+vectors,HEAD_PARAMETER_NAMES=head,FEATURE_PARAMETER_NAMES=vectors,TRAINABLE_PARAMETER_NAMES=head,ENCODED_WIDTH=64,_require=require,checkpoint_digest=digest,split=SimpleNamespace(_branch_digests=split_ns['_branch_digests']))
    selected(SOURCE.with_name('legal_span_actor_boundary.py'),{'_finite_shape','_trainable_shapes','_inactive_state'},old)
    inactive=old['_inactive_state']
    old['actor_ce']=SimpleNamespace(_inactive_state=inactive)
    selected(SOURCE.with_name('legal_span_actor_features.py'),{'_inactive_state','_branch_digests'},old)
    features=SimpleNamespace(HEAD_PARAMETER_NAMES=head,FEATURE_PARAMETER_NAMES=vectors,MODEL_PARAMETER_NAMES=base+head+vectors,
        _inactive_state=old['_inactive_state'],_branch_digests=old['_branch_digests'],_implementation=lambda:dict(inert='features'))
    cond_names=('conditions_presence.weight','conditions_presence.bias')
    cond_ns=dict(copy=copy,math=math,_require=require,ENCODED_WIDTH=64,INACTIVE_ROWS=(0,1,4,5,6,7))
    selected(SOURCE.with_name('legal_span_conditions_presence.py'),{'_finite_shape','_trainable_shapes','_inactive_state'},cond_ns)
    conditions=SimpleNamespace(MODEL_PARAMETER_NAMES=features.MODEL_PARAMETER_NAMES+cond_names,TRAINABLE_PARAMETER_NAMES=cond_names,
        _inactive_state=cond_ns['_inactive_state'],_implementation=lambda:dict(inert='conditions'),_validated=lambda p:require(set(p['model_state'])==set(features.MODEL_PARAMETER_NAMES+cond_names),'source42'))
    parent_path=SOURCE.with_name('legal_span_actor_refinement.py')
    parent_ns=dict(copy=copy,_require=require,features=features)
    selected(parent_path,{'_model'},parent_ns)
    refinement=SimpleNamespace(MODEL_PARAMETER_NAMES=conditions.MODEL_PARAMETER_NAMES,BASE_PARAMETER_NAMES=base+cond_names,
        HEAD_PARAMETER_NAMES=head,FEATURE_PARAMETER_NAMES=vectors,TRAINABLE_PARAMETER_NAMES=head+vectors,
        _model=parent_ns['_model'],_implementation=lambda:dict(inert='refinement'),
        _validated=lambda p:require(set(p['model_state'])==set(conditions.MODEL_PARAMETER_NAMES),'source42'))
    ns=dict(__file__=str(SOURCE),copy=copy,hashlib=hashlib,json=json,math=math,Path=Path,features=features,conditions=conditions,refinement=refinement,targeted=targeted,continuation=SimpleNamespace(_context_contract=copy.deepcopy,_implementation=lambda:dict(inert='continuation')),span=span)
    names={'_finite_shape','_trainable_shapes','_initial_state','_inactive_state','_all_zero','_partition','_policy','_validate_policy','_capture_implementation','_implementation','_source','_training_records','_source_state_map','_branch_digests','_model','_configure_parameters','_validate_optimizer_state','_origin','build_checkpoint','_validated','_loss','_validate_objective_entry','_validate_freeze_entry','_validate_feature_entry','_row_invariants','train_decoder'}
    nodes=[]
    for n in ast.parse(SOURCE.read_bytes()).body:
        if isinstance(n,ast.Assign) or isinstance(n,ast.FunctionDef) and n.name in names:nodes.append(n)
    ns['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#detached','exec'),ns)
    return ns

def fixture(ns):
    state={n:[float(i)] for i,n in enumerate(ns['MODEL_PARAMETER_NAMES'])}
    for n,shape in ns['_trainable_shapes']().items():state[n]=[[.1*(r+1)]*64 for r in range(6)] if len(shape)==2 else ([.23]*64 if shape==(64,) else [.1]*6)
    for n in ('conditions_presence.weight','presence.weight'):state[n]=[[.31+r*.01]*64 for r in range(8)]
    for n in ('conditions_presence.bias','presence.bias'):state[n]=[.17+r*.01 for r in range(8)]
    rows=[dict(id='synthetic-'+str(i),source_text='actor acts object') for i in range(168)]
    contract=dict(mode='source-only',dimension=384);child=dict(context_contract=contract,context_contract_sha256=digest(contract))
    parent=dict(model_state=state,progress=dict(optimizer_steps=32),training_manifest_sha256=digest(rows),config=dict(hidden_size=32,latent_dimension=384,latent_enabled=False),initial_continuation_checkpoint=child,source_parent_checkpoint_sha256='a'*64,source_parent_model_state_sha256='b'*64)
    parent['source_frozen36_state_sha256']=digest({k:state[k] for k in ns['BASE_PARAMETER_NAMES']});parent['optimizer_state']={'sentinel_nonzero_donor_moments':.37};ns['SOURCE_ACTOR_REFINEMENT_SHA256']=digest(parent);ns['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256']=digest(state);ns['SOURCE_FROZEN36_SHA256']=parent['source_frozen36_state_sha256']
    return parent,rows,ns['build_checkpoint'](parent,rows,context_contract=contract)

def moments(ns,steps):
    result={}
    for n,shape in ns['_trainable_shapes']().items():
        a=[[0.]*64 for _ in range(6)] if len(shape)==2 else [0.]*shape[0]
        result[n]=dict(step=steps,exp_avg=copy.deepcopy(a),exp_avg_sq=copy.deepcopy(a))
    return dict(schema='adam-default-betas-eps/v1',parameters=result if steps else {})

def feature_entry():
    batch=dict(optimizer_step=1,indices=[7],ids=['synthetic-7'])
    e=dict(batch,gradients_finite_connected=True,trained_start_requirements_checked=True,fresh_zero_initialization_assumed=False)
    for label in ('query','gate','context','residual'):e.update({label+'_gradient_l2':.2,label+'_gradient_exact_zero':False})
    for label in ('query','gate'):e.update({label+'_before_sha256':'a'*64,label+'_after_sha256':'b'*64,label+'_changed':True,label+'_Adam_moments_exact_zero':False,label+'_exp_avg_sha256':'c'*64,label+'_exp_avg_sq_sha256':'d'*64})
    return e,batch

class Contracts(unittest.TestCase):
    def setUp(self):self.ns=namespace()
    def test_policy_uses_trained_F15_six_tensor_fresh_Adam_and_fixed_ranking(self):
        n=self.ns;p=n['_policy']('actor-context-ranking-hinge');n['_validate_policy'](p);part=p['parameter_partition']
        self.assertEqual(n['SOURCE_ACTOR_REFINEMENT_SHA256'],'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
        self.assertEqual(n['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256'],'a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42')
        self.assertEqual((len(part['model_parameter_names']),len(part['frozen_parameter_names']),len(part['trainable_parameter_names'])),(42,36,6))
        self.assertEqual((part['stored_trainable_scalar_count'],part['active_trainable_scalar_count'],part['inactive_stored_scalar_count']),(908,258,650))
        self.assertTrue(p['objective_policy']['actor_ranking_enabled']);self.assertFalse(p['actor_features']['fresh_zero_initialization_assumed']);self.assertFalse(p['inherited_optimizer_moments'])
        self.assertTrue(set(('conditions_presence.weight','conditions_presence.bias'))<=set(part['frozen_parameter_names']))
        for mutate in (lambda x:x['objective_policy'].update(actor_ranking_enabled=False),lambda x:x['optimizer'].update(weight_decay=.01),lambda x:x['actor_features'].update(fresh_zero_initialization_assumed=True)):
            bad=copy.deepcopy(p);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_policy'](bad)
        for kw in (dict(seed=True),dict(batch_size=11),dict(batch_order_seed=1730)):
            with self.assertRaises(ValueError):n['_policy']('actor-context-ranking-hinge',**kw)
    def test_checkpoint_preserves_trained_query_gate_conditions_and_separates_frozen36(self):
        n=self.ns;parent,rows,cp=fixture(n);n['_validated'](cp)
        self.assertEqual(cp['model_state'],parent['model_state']);self.assertIsNot(cp['model_state'],parent['model_state'])
        self.assertEqual(cp['model_state']['actor_attention.query'],[.23]*64)
        expected=digest({k:parent['model_state'][k] for k in n['BASE_PARAMETER_NAMES']})
        self.assertEqual(cp['source_frozen36_state_sha256'],expected);self.assertNotEqual(expected,n['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256'])
        cp['model_state']['actor_attention.query'][0]=9.;self.assertEqual(parent['model_state']['actor_attention.query'][0],.23)
        for mutate in (lambda c:c['model_state']['actor_attention.query'].pop(),lambda c:c['model_state']['actor_context.gate'].__setitem__(0,True),lambda c:c['model_state']['actor_context.gate'].__setitem__(0,float('nan')),lambda c:c['model_state']['actor_attention.query'].__setitem__(0,float('inf')),lambda c:c['model_state']['conditions_presence.bias'].__setitem__(2,9.),lambda c:c.update(source_frozen36_state_sha256='f'*64)):
            bad=fixture(n)[2];mutate(bad)
            with self.assertRaises(ValueError):n['_validated'](bad)
        parent,rows,initial=fixture(n);continued=copy.deepcopy(initial);continued['model_state']['actor_attention.query'][0]+=.01;continued['model_state']['actor_context.gate'][0]+=.02
        continued['progress']=dict(epochs_completed=0,row_cursor=12,optimizer_steps=1);continued['parent_checkpoint_sha256']=digest(initial);continued['optimizer_state']=moments(n,1)
        for key in ('exp_avg','exp_avg_sq'):continued['optimizer_state']['parameters']['actor_attention.query'][key][0]=.04
        n['_validated'](continued)
    def test_first_step_query_moments_allowed_inactive650_and_shapes_fail_closed(self):
        n=self.ns;good=moments(n,1)
        for key in ('exp_avg','exp_avg_sq'):good['parameters']['actor_attention.query'][key][0]=.3
        n['_validate_optimizer_state'](good,1)
        for mutate in (lambda m:m['parameters']['actor_start.weight']['exp_avg'][1].__setitem__(0,.1),lambda m:m['parameters']['actor_end.bias']['exp_avg_sq'].__setitem__(5,.1),lambda m:m['parameters']['actor_context.gate']['exp_avg'].pop(),lambda m:m['parameters']['actor_attention.query']['exp_avg_sq'].__setitem__(0,-.1),lambda m:m['parameters'].pop('actor_context.gate')):
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_optimizer_state'](bad,1)
    def test_trained_first_query_gradient_change_nonzero_moments_accepted(self):
        n=self.ns;e,b=feature_entry();n['_validate_feature_entry'](e,b)
        for mutate in (lambda x:x.update(fresh_zero_initialization_assumed=True),lambda x:x.update(query_gradient_l2=float('nan')),lambda x:x.update(query_changed=False),lambda x:x.update(gradients_finite_connected=False),lambda x:x.update(trained_start_requirements_checked=False)):
            bad=copy.deepcopy(e);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_feature_entry'](bad,b)
        e['optimizer_step']=b['optimizer_step']=2;e['trained_start_requirements_checked']=False;n['_validate_feature_entry'](e,b)
    def test_freeze_trace_allows_actor_changes_protects_F15_conditions_and_frozen36(self):
        n=self.ns;parent,rows,cp=fixture(n);before=n['_branch_digests'](cp['model_state']);after=copy.deepcopy(before)
        for key in ('actor_head_state_sha256','actor_attention_query_sha256','actor_context_gate_sha256'):after[key]='e'*64
        b=dict(optimizer_step=1,indices=[0],ids=['synthetic-0'])
        e=dict(b,source_frozen36_state_sha256=cp['source_frozen36_state_sha256'],frozen_before=before['frozen_nonactor36_state_sha256'],frozen_after=before['frozen_nonactor36_state_sha256'],inactive_before=before['inactive_actor_head_rows_sha256'],inactive_after=before['inactive_actor_head_rows_sha256'],frozen_head_sample_sha256='f'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,inactive_moments_zero=True,changed_parameter_names=list(n['TRAINABLE_PARAMETER_NAMES']),completed_returned_update=True,branch_digests_before=before,branch_digests_after=after)
        n['_validate_freeze_entry'](e,b)
        for mutate in (lambda x:x['branch_digests_after'].update(conditions_presence_state_sha256='a'*64),lambda x:x.update(frozen_after='a'*64),lambda x:x.update(inactive_after='a'*64),lambda x:x.update(inactive_moments_zero=False),lambda x:x['changed_parameter_names'].append('conditions_presence.bias')):
            bad=copy.deepcopy(e);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_freeze_entry'](bad,b)
    def test_factory_keeps_actor_forward_differentiable_and_conditions_frozen_full8(self):
        n=self.ns;events=[];state=dict(rng=19,depth=0)
        class RNG:
            def __init__(self,v):self.v=v
            def clone(self):return RNG(self.v)
        class Guard:
            def __enter__(self):state['depth']+=1
            def __exit__(self,*args):state['depth']-=1
        class Pooled:
            def __getitem__(self,key):return self
            def __mul__(self,other):return self
            def sum(self,axis):return self
            def __truediv__(self,other):return self
        pooled=Pooled()
        class Pairs:
            def __init__(self,v):self.v=v
            def __getitem__(self,key):return Pairs(self.v[key[1]])
            def reshape(self,*shape):require(shape==(-1,4,2),'full8');return Pairs([self.v[i:i+2] for i in range(0,8,2)])
        class Head:
            def __init__(self):self.v=list(range(8))
            def __call__(self,p):require(p is pooled and state['depth']==1,'conditions projection frozen');events.append('conditions-full8');return Pairs(list(self.v))
        original=dict(modality=object(),presence=Pairs([[0,1],[2,3],[4,5],[6,7]]),start=object(),end=object())
        class Base:
            def __init__(self):self.presence=Head()
            def _features(self,*args):require(state['depth']==1 and args[-1] is True,'additional frozen span path');events.append('extra-span');return pooled,pooled
            def forward(self,*args,enabled=True):require(state['depth']==0,'actor path must retain autograd');events.append(('actor-forward',enabled));return original
        n['features']._model=lambda torch,config:Base()
        def cat(values,dim):require(dim==1,'presence pairs');return Pairs([pair for value in values for pair in value.v])
        torch=SimpleNamespace(get_rng_state=lambda:RNG(state['rng']),equal=lambda a,b:a.v==b.v,no_grad=Guard,cat=cat)
        model=n['_model'](torch,{});self.assertIsNot(model.conditions_presence,model.presence);self.assertIsNot(model.conditions_presence.v,model.presence.v)
        model.conditions_presence.v[2:4]=[70,71];out=model.forward(None,None,pooled,None,enabled=False)
        self.assertEqual(out['presence'].v,[[0,1],[70,71],[4,5],[6,7]])
        for k in ('modality','start','end'):self.assertIs(out[k],original[k])
        self.assertEqual(events,[('actor-forward',False),'extra-span','conditions-full8']);self.assertEqual(model.presence.v,list(range(8)));self.assertEqual(set(model._conditions_forward_accounting.values()),{1})
        self.assertIn('actor_features_model_forwards',model._conditions_forward_accounting);self.assertNotIn('frozen_actor_features_model_forwards',model._conditions_forward_accounting)
        self.assertEqual((state['depth'],state['rng']),(0,19))
        def unsafe(torch,config):state['rng']+=1;return Base()
        n['features']._model=unsafe
        with self.assertRaisesRegex(ValueError,'ambient CPU RNG'):n['_model'](torch,{})
    def test_configuration_selects_exact6_independent_storages_and_freezes36(self):
        n=self.ns
        class Parameter:
            def __init__(self,shape,key):self.shape=shape;self.key=key;self.grad=object();self.requires_grad=None
            def untyped_storage(self):return SimpleNamespace(data_ptr=lambda:self.key)
            def numel(self):return math.prod(self.shape)
            def requires_grad_(self,v):self.requires_grad=v
        shapes=n['_trainable_shapes']();params={name:Parameter(shapes.get(name,(1,)),i) for i,name in enumerate(n['MODEL_PARAMETER_NAMES'])}
        model=SimpleNamespace(named_parameters=lambda:list(params.items()));named,chosen=n['_configure_parameters'](model)
        self.assertEqual(chosen,[params[name] for name in n['TRAINABLE_PARAMETER_NAMES']]);self.assertTrue(all(p.grad is None and p.requires_grad is (name in n['TRAINABLE_PARAMETER_NAMES']) for name,p in params.items()))
        params['conditions_presence.bias'].key=params['actor_attention.query'].key
        with self.assertRaisesRegex(ValueError,'alias'):n['_configure_parameters'](model)
    def test_actor_ranking_reuses_loss_object_and_records_training_domain(self):
        n=self.ns;seen={};records=n['_training_records']([dict(id='s'+str(i),source_text='actor acts object') for i in range(168)])[:1]
        class Scalar:
            def detach(self):return self
            def __float__(self):return 1.25
        value=Scalar()
        def loss(torch,forward,rows,policy):seen.update(output=forward(None),rows=rows,policy=policy);return value,dict(actor_hinge_applied=True,total_loss=1.25)
        n['targeted']._loss=loss;out=object();actual,d=n['_loss'](None,out,records,[4],n['_policy']('actor-context-ranking-hinge'))
        self.assertIs(actual,value);self.assertIs(seen['output'],out);self.assertTrue(seen['policy']['actor_ranking_enabled']);self.assertEqual(d['rows'][0]['training_index'],4);self.assertEqual(d['rows'][0]['actor_gold_coordinates'],[0,0]);self.assertEqual(d['batch_denominator'],1)
        with self.assertRaises(ValueError):n['_loss'](None,out,records,[],n['_policy']('actor-context-ranking-hinge'))
    def test_all42_source_identity_map_and_exact_donor_pins_fail_closed(self):
        n=self.ns;parent,rows,cp=fixture(n)
        self.assertEqual(cp['model_source_state_map'],{name:name for name in n['MODEL_PARAMETER_NAMES']})
        for mutate in (
            lambda x:x['model_source_state_map'].pop('conditions_presence.bias'),
            lambda x:x['model_source_state_map'].update({'actor_context.gate':'actor_attention.query'}),
            lambda x:x['source_actor_refinement_checkpoint']['progress'].update(optimizer_steps=31),
            lambda x:x.update(source_actor_refinement_checkpoint_sha256='e'*64),
            lambda x:x.update(source_actor_refinement_model_state_sha256='e'*64)):
            bad=copy.deepcopy(cp);mutate(bad)
            with self.assertRaises(ValueError):n['_validated'](bad)
    def test_objective_joins_source_gold_domain_and_selected_hinge_trace(self):
        n=self.ns;target=n['targeted'];policy=n['_policy']('actor-context-ranking-hinge')
        rows=n['_training_records']([dict(id='s'+str(i),source_text='actor acts object') for i in range(168)])[:1]
        record=rows[0];count,gold,others,domain=target._actor_record(record)
        chosen=target._choose_actor_wrong([0.,0.,0.],[0.,0.,0.],count,gold,others)
        chosen.update(selection_implementation='vectorized_detached_source_boundary_gather',row_position=0,
            id=record['id'],source_sha256=hashlib.sha256(record['source_text'].encode()).hexdigest(),
            actor_hinge_value=1.,hinge_active=True,gradient_enabled_by_policy=True,
            zero_domain_differentiable_zero=False,teacher_forced_compatibility=True,semantic_compatibility_verified=False)
        base=dict(schema='targeted-source-span-objective-diagnostics/v1',main_loss=1.,actor_hinge_mean=1.,
            actor_hinge_applied=True,actor_hinge_coefficient=.25,total_loss=1.25,
            presence_CE_means=dict(conditions=0.,exceptions=0.),rows=[chosen],teacher_forcing=True,
            evaluation_references_used=False,semantic_compatibility_verified=False)
        class Scalar:
            def detach(self):return self
            def __float__(self):return 1.25
        target._loss=lambda *args:(Scalar(),copy.deepcopy(base))
        _,details=n['_loss'](None,object(),rows,[0],policy)
        batch=dict(optimizer_step=1,indices=[0],ids=[record['id']],loss=1.25)
        entry=dict(optimizer_step=1,indices=[0],ids=[record['id']],details=details)
        n['_validate_objective_entry'](entry,batch,policy)
        for mutate in (
            lambda x:x['details']['rows'][0].update(source_sha256='a'*64),
            lambda x:x['details']['rows'][0].update(training_index=1),
            lambda x:x['details']['rows'][0].update(compatible_wrong_domain_sha256='a'*64),
            lambda x:x['details']['rows'][0].update(compatible_wrong_candidate_count=True),
            lambda x:x['details']['rows'][0]['present_gold_nonactor_coordinates'].update(action=[2,2]),
            lambda x:x['details']['base_objective'].update(actor_hinge_applied=False),
            lambda x:x['details']['base_objective'].update(actor_hinge_coefficient=.5),
            lambda x:x['details']['base_objective']['rows'][0].update(chosen_wrong_coordinates=[1,1]),
            lambda x:x['details']['base_objective']['rows'][0].update(actor_hinge_value=0.),
            lambda x:x['details'].update(total_loss=1.)):
            bad=copy.deepcopy(entry);mutate(bad)
            with self.assertRaises(ValueError):n['_validate_objective_entry'](bad,batch,policy)
    def test_fixed_schedule32_updates384_occurrences_and_bounds_before_restore(self):
        n=self.ns;p=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0);occ=[]
        for step in range(32):
            indices=n['targeted']._batch_indices(168,p,12,1729);self.assertEqual(len(indices),12);occ.extend(indices);p=n['targeted']._advance_progress(p,len(indices),168)
        self.assertEqual(len(occ),384);self.assertEqual(set(occ[:168]),set(range(168)));self.assertEqual(p,dict(epochs_completed=2,row_cursor=48,optimizer_steps=32))
        n['_validated']=lambda cp:(_ for _ in ()).throw(AssertionError('bounds must precede checkpoint/model access'))
        for kw in (dict(max_steps=33),dict(max_steps=True),dict(max_seconds=float('nan')),dict(max_seconds=33)):
            with self.assertRaises(ValueError):n['train_decoder'](None,(),**kw)

if __name__=='__main__':unittest.main()

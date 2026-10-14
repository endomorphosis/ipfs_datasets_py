"""Detached stdlib conditions-head controls; never import production or numerical modules."""
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

SOURCE=Path(__file__).resolve().parents[4]/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_presence.py'
PARENT=SOURCE.with_name('legal_span_actor_features.py')
RETAINED_TEST=Path(__file__).with_name('test_legal_span_actor_features_contracts.py')

def require(value,message):
    if not value:raise ValueError(message)
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def digest(value):return hashlib.sha256(raw(value)).hexdigest()
def deny(name,*args,**kwargs):raise AssertionError('no production/numerical import: '+name)
def selected(path,names,ns):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in nodes}==set(names),'exact detached owner set')
    require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'no detached imports')
    ns['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#detached','exec'),ns);return ns

def namespace():
    # Reuse only retained stdlib fixture helpers, with their original owner paths.
    base=dict(__file__=str(RETAINED_TEST),ast=ast,builtins=builtins,copy=copy,hashlib=hashlib,json=json,math=math,Path=Path,
        random=random,re=re,struct=struct,SimpleNamespace=SimpleNamespace,SOURCE=PARENT,SPLIT=SOURCE.with_name('legal_span_split_features.py'),
        PARENT=SOURCE.with_name('legal_span_actor_boundary.py'),TARGETED=SOURCE.with_name('legal_span_targeted_loss.py'))
    selected(RETAINED_TEST,{'require','raw','digest','deny_import','detached','owner_namespace'},base)
    old=base['owner_namespace']();names=old['MODEL_PARAMETER_NAMES']
    branches=('modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256','span_path_state_sha256',
        'dormant_latent_state_sha256','frozen_base34_state_sha256','actor_head_state_sha256','inactive_actor_head_rows_sha256',
        'actor_attention_query_sha256','actor_context_gate_sha256')
    parent=SimpleNamespace(MODEL_PARAMETER_NAMES=names,_implementation=lambda:dict(parent='inert'),
        _validated=lambda source:require(set(source['model_state'])==set(names),'exact40'),
        _branch_digests=lambda state:dict.fromkeys(branches,digest(state)))
    ns=dict(__file__=str(SOURCE),__name__='detached_conditions',copy=copy,hashlib=hashlib,json=json,math=math,Path=Path,
        parent=parent,targeted=old['targeted'],continuation=old['continuation'],span=old['span'])
    ns['__builtins__']=dict(vars(builtins),__import__=deny)
    body=[n for n in ast.parse(SOURCE.read_bytes()).body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    exec(compile(ast.Module(body=body,type_ignores=[]),str(SOURCE)+'#detached','exec'),ns);return ns

def fixture(ns):
    rows=[dict(id='synthetic-'+str(i),source_text='actor acts object') for i in range(168)]
    state={name:[float(i)] for i,name in enumerate(ns['BASE_PARAMETER_NAMES'])}
    state['presence.weight']=[[float(i+j)/100 for j in range(64)] for i in range(8)]
    state['presence.bias']=[float(i)/10 for i in range(8)]
    contract=dict(mode='source-only',dimension=384);child=dict(context_contract=contract,context_contract_sha256=digest(contract))
    parent=dict(model_state=state,progress=dict(optimizer_steps=32),training_manifest_sha256=digest(rows),
        config=dict(hidden_size=32,latent_dimension=384,latent_enabled=False),initial_continuation_checkpoint=child,
        source_parent_checkpoint_sha256='a'*64,source_parent_model_state_sha256='b'*64)
    ns['SOURCE_ACTOR_FEATURES_SHA256']=digest(parent);ns['SOURCE_ACTOR_FEATURES_MODEL_SHA256']=digest(state)
    return parent,rows,ns['build_checkpoint'](parent,rows,context_contract=contract)

def moments(ns,step):
    zero=lambda shape:[[0.]*64 for _ in range(8)] if len(shape)==2 else [0.]*8
    return dict(schema='adam-default-betas-eps/v1',parameters={name:dict(step=step,exp_avg=zero(shape),exp_avg_sq=zero(shape)) for name,shape in ns['_trainable_shapes']().items()})

class Contracts(unittest.TestCase):
    def setUp(self):self.ns=namespace()
    def test_policy_geometry_and_real_parent_pins(self):
        ns=self.ns;p=ns['_policy']('conditions-presence-ce');ns['_validate_policy'](p)
        self.assertEqual(ns['SOURCE_ACTOR_FEATURES_SHA256'],'b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3')
        self.assertEqual(ns['SOURCE_ACTOR_FEATURES_MODEL_SHA256'],'c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab')
        part=ns['_partition']();self.assertEqual((len(part['model_parameter_names']),len(part['frozen_parameter_names']),len(part['trainable_parameter_names'])),(42,40,2))
        self.assertEqual((part['stored_trainable_scalar_count'],part['active_trainable_scalar_count'],part['inactive_stored_scalar_count']),(520,130,390))
        self.assertEqual(part['active_head_rows'],[2,3]);self.assertEqual(part['inactive_head_rows'],[0,1,4,5,6,7])
        self.assertFalse(p['objective_policy']['training_row_reweighting']);self.assertEqual(p['feature_paths_per_source_model_forward'],3)
        for mutate in (lambda p:p['objective_policy'].update(actor_ranking_enabled=True),lambda p:p.update(objective='modality-ce'),lambda p:p['optimizer'].update(weight_decay=.01)):
            bad=copy.deepcopy(p);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_policy'](bad)
    def test_full8_independent_copy_parent40_frozen_and_active_shapevalidation(self):
        ns=self.ns;parent,rows,cp=fixture(ns);ns['_validated'](cp)
        self.assertEqual(raw(cp['model_state']['conditions_presence.weight']),raw(parent['model_state']['presence.weight']))
        self.assertIsNot(cp['model_state']['conditions_presence.weight'],parent['model_state']['presence.weight'])
        for mutate in (lambda c:c['model_state']['conditions_presence.weight'][0].__setitem__(0,9.),
                       lambda c:c['model_state']['conditions_presence.weight'][2].pop(),
                       lambda c:c['model_state']['conditions_presence.bias'].__setitem__(2,float('nan')),
                       lambda c:c['model_state']['conditions_presence.bias'].__setitem__(2,True),
                       lambda c:c['model_state']['actor_attention.query'].__setitem__(0,9.),
                       lambda c:c['config'].update(latent_enabled=True)):
            bad=copy.deepcopy(cp);mutate(bad)
            with self.assertRaises(ValueError):ns['_validated'](bad)
    def test_adam_owns_only_two_new_tensors_inactive390_moments_zero(self):
        ns=self.ns;good=moments(ns,1);ns['_validate_optimizer_state'](good,1)
        good['parameters']['conditions_presence.bias']['exp_avg'][2]=.2;ns['_validate_optimizer_state'](good,1)
        for row in ns['INACTIVE_ROWS']:
            bad=copy.deepcopy(good);bad['parameters']['conditions_presence.weight']['exp_avg'][row][0]=.1
            with self.assertRaises(ValueError):ns['_validate_optimizer_state'](bad,1)
        for mutate in (lambda s:s['parameters'].pop('conditions_presence.bias'),lambda s:s['parameters']['conditions_presence.bias'].update(step=2),lambda s:s['parameters']['conditions_presence.bias']['exp_avg_sq'].__setitem__(2,-.1)):
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_optimizer_state'](bad,1)
    def test_loss_meanallrows_onlyconditionspair_and_scalar_identity(self):
        ns=self.ns;seen={}
        class Value:
            requires_grad=True
            def __getitem__(self,key):seen['slice']=key;return self
            def detach(self):return self
            def tolist(self):return [[1.,2.],[3.,4.]]
        class Scalar:
            def detach(self):return self
            def __float__(self):return 1.25
        value=Value();loss=Scalar()
        def ce(logits,targets):seen.update(logits=logits,targets=targets);return loss
        torch=SimpleNamespace(nn=SimpleNamespace(functional=SimpleNamespace(cross_entropy=ce)),tensor=lambda x:x)
        records=[dict(id='s0',labels=dict(presence=[True,True,True,False,False,False])),dict(id='s1',labels=dict(presence=[True,True,True,True,False,False]))]
        actual,details=ns['_loss'](torch,dict(presence=value),records,[0,1],ns['_policy']('conditions-presence-ce'))
        self.assertIs(actual,loss);self.assertEqual(seen['slice'],(slice(None),1,slice(None)));self.assertEqual(seen['targets'],[0,1]);self.assertEqual(details['batch_denominator'],2)
        batch=dict(optimizer_step=1,indices=[0,1],ids=['s0','s1'],loss=1.25);entry={k:batch[k] for k in ('optimizer_step','indices','ids')};entry['details']=details
        ns['_validate_objective_entry'](entry,batch,ns['_policy']('conditions-presence-ce'))
        for mutate in (lambda e:e['details'].update(actor_hinge_applied=True),lambda e:e['details'].update(evaluation_references_used=True),lambda e:e['details']['rows'][0].update(conditions_present=0),lambda e:e['details']['rows'][0].update(conditions_logits=[1.])):
            bad=copy.deepcopy(entry);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_objective_entry'](bad,batch,ns['_policy']('conditions-presence-ce'))
    def test_factory_preserves_parent_heads_copies_full8_and_uses_one_extra_frozen_path(self):
        ns=self.ns;events=[];state=dict(rng=17,depth=0)
        class RNG:
            def __init__(self,value):self.value=value
            def clone(self):return RNG(self.value)
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
            def __init__(self,values):self.values=values
            def __getitem__(self,key):
                batch,pair,width=key
                return Pairs(self.values[pair])
            def reshape(self,*shape):
                require(shape==(-1,4,2),'full8 reshape only')
                return Pairs([self.values[i:i+2] for i in range(0,8,2)])
        class Head:
            def __init__(self):self.values=list(range(8))
            def __call__(self,value):
                require(value is pooled and state['depth']==0,'copied head outside no_grad on pooled frozen features')
                events.append('new-full8-head');return Pairs(list(self.values))
        original=dict(modality=object(),presence=Pairs([[0,1],[2,3],[4,5],[6,7]]),start=object(),end=object())
        class Base:
            def __init__(self):self.presence=Head()
            def _features(self,*args):
                require(state['depth']==1,'all feature computation frozen')
                events.append(('features',args[-1]));return pooled,pooled
            def forward(self,*args,enabled=True):
                require(state['depth']==1,'parent forward frozen')
                events.append('parent-forward')
                self._features(*args,enabled,False);self._features(*args,enabled,True)
                return original
        def factory(torch,config):events.append('parent-construction');return Base()
        ns['parent']._model=factory
        def cat(values,dim):
            require(dim==1,'presence pair concat');return Pairs([pair for value in values for pair in value.values])
        torch=SimpleNamespace(get_rng_state=lambda:RNG(state['rng']),equal=lambda a,b:a.value==b.value,no_grad=Guard,cat=cat)
        model=ns['_model'](torch,{})
        self.assertEqual(state['rng'],17);self.assertIsNot(model.conditions_presence,model.presence)
        self.assertIsNot(model.conditions_presence.values,model.presence.values)
        def call():return model.forward(None,None,pooled,None,enabled=False)
        baseline=call();self.assertEqual(baseline['presence'].values,original['presence'].values)
        model.conditions_presence.values[2:4]=[100,101]
        altered=call();self.assertEqual(altered['presence'].values,[[0,1],[100,101],[4,5],[6,7]])
        for key in ('modality','start','end'):self.assertIs(altered[key],original[key])
        self.assertEqual(model.presence.values,list(range(8)))
        self.assertEqual(events.count('parent-forward'),2);self.assertEqual(events.count('new-full8-head'),2)
        self.assertEqual(events.count(('features',True)),4);self.assertEqual(events.count(('features',False)),2)
        self.assertEqual(set(model._conditions_forward_accounting.values()),{2});self.assertEqual(len(model._conditions_forward_accounting),6)
        self.assertEqual(state['depth'],0)
        def unsafe_factory(torch,config):state['rng']+=1;return Base()
        ns['parent']._model=unsafe_factory
        with self.assertRaisesRegex(ValueError,'ambient CPU RNG'):ns['_model'](torch,{})
    def test_freeze_trace_rejects_parent_heads_inactive_moments_and_unregistered_changes(self):
        ns=self.ns;parent,rows,cp=fixture(ns);before=ns['_branch_digests'](cp['model_state'])
        batch=dict(optimizer_step=1,indices=[0],ids=['synthetic-0'])
        entry=dict(batch,frozen_before=ns['SOURCE_ACTOR_FEATURES_MODEL_SHA256'],frozen_after=ns['SOURCE_ACTOR_FEATURES_MODEL_SHA256'],
            inactive_before=before['inactive_conditions_presence_rows_sha256'],inactive_after=before['inactive_conditions_presence_rows_sha256'],
            frozen_head_sample_sha256='a'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,
            inactive_gradients_zero=True,inactive_moments_zero=True,completed_returned_update=True,
            changed_parameter_names=['conditions_presence.weight'],branch_digests_before=before,branch_digests_after=dict(before))
        ns['_validate_freeze_entry'](entry,batch)
        for mutate in (lambda e:e.update(inactive_moments_zero=False),lambda e:e.update(frozen_gradients_none=False),
                       lambda e:e.update(changed_parameter_names=['actor_context.gate']),
                       lambda e:e['branch_digests_after'].update(actor_attention_query_sha256='b'*64),
                       lambda e:e.update(inactive_after='c'*64),lambda e:e.update(frozen_head_sample_sha256='not-a-digest')):
            bad=copy.deepcopy(entry);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_freeze_entry'](bad,batch)
    def test_parameter_configuration_freezes_all40_and_refuses_storage_alias(self):
        ns=self.ns
        class Parameter:
            def __init__(self,shape,pointer):self.shape=shape;self.pointer=pointer;self.grad='old';self.enabled=None
            def untyped_storage(self):return self
            def data_ptr(self):return self.pointer
            def numel(self):return math.prod(self.shape)
            def requires_grad_(self,enabled):self.enabled=enabled
        shapes=ns['_trainable_shapes']()
        named={name:Parameter(shapes.get(name,(1,)),index) for index,name in enumerate(ns['MODEL_PARAMETER_NAMES'])}
        model=SimpleNamespace(named_parameters=lambda:list(named.items()))
        actual,selected=ns['_configure_parameters'](model)
        self.assertEqual(selected,[named[name] for name in ns['TRAINABLE_PARAMETER_NAMES']])
        self.assertEqual(sum(p.enabled is True for p in actual.values()),2)
        self.assertEqual(sum(p.enabled is False for p in actual.values()),40)
        self.assertTrue(all(p.grad is None for p in actual.values()))
        named['conditions_presence.bias'].pointer=named['presence.bias'].pointer
        with self.assertRaisesRegex(ValueError,'storage alias'):ns['_configure_parameters'](model)
    def test_exact32schedule384_same168_no_mined_rows(self):
        ns=self.ns;p=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0);allrows=[]
        for _ in range(32):
            ids=ns['targeted']._batch_indices(168,p,12,1729);allrows+=ids;p=ns['targeted']._advance_progress(p,12,168)
        self.assertEqual(len(allrows),384);self.assertEqual(set(allrows),set(range(168)));self.assertEqual(p,dict(epochs_completed=2,row_cursor=48,optimizer_steps=32))
    def test_bounds_before_restore_and_no_fullproduction_imports(self):
        ns=self.ns
        for args in (dict(max_steps=33),dict(max_steps=True),dict(max_seconds=float('nan')),dict(max_seconds=33)):
            with self.assertRaises(ValueError):ns['train_decoder']({},[],**args)
        with self.assertRaisesRegex(AssertionError,'no production/numerical import: torch'):ns['_restore']({})
        for rows in ([],[{}]*129):
            with self.assertRaises(ValueError):ns['captured_inference'](None,None,None,None,rows)

if __name__=='__main__':unittest.main()

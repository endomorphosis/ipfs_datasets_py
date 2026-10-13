"""Inert split-path contracts; no producer/model/numerical library imports.

Selected AST definitions execute with explicit parameter/scalar/module fakes.
These tests establish source contracts, not actual gradients or legal accuracy.
"""
from __future__ import annotations
import ast
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

SOURCE=Path(__file__).resolve().parents[4]/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py'
TARGETED=SOURCE.with_name('legal_span_targeted_loss.py')
ORIGINAL=(
    'byte_embedding.weight','token_projection.weight','token_projection.bias',
    'encoder.weight_ih_l0','encoder.weight_hh_l0','encoder.bias_ih_l0','encoder.bias_hh_l0',
    'encoder.weight_ih_l0_reverse','encoder.weight_hh_l0_reverse','encoder.bias_ih_l0_reverse','encoder.bias_hh_l0_reverse',
    'modality.weight','modality.bias','presence.weight','presence.bias','start.weight','start.bias','end.weight','end.bias',
    'latent_down.weight','latent_down.bias','latent_up.weight','latent_up.bias')
FEATURES=ORIGINAL[:11]
FACETS=ORIGINAL[13:19]
LATENT=ORIGINAL[19:]
SPLIT=tuple('span_'+name for name in FEATURES)
NAMES=ORIGINAL+SPLIT
TRAINABLE=SPLIT+FACETS
BRANCH_FIELDS=('modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256',
    'span_path_state_sha256','dormant_latent_state_sha256')
FLAGS=('qualified','admitted','formalized','roundtrip_ok','proof_authority','semantic_correctness_verified','promotion_performed','publication_performed')
ZERO=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0)

def detach(path,names,ns):
    tree=ast.parse(path.read_bytes());selected={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names}
    if set(selected)!=set(names):raise AssertionError('missing inert contract')
    for node in selected.values():
        if node.decorator_list or any(isinstance(n,(ast.Import,ast.ImportFrom)) for n in ast.walk(node)):
            raise AssertionError('detached functions refuse imports/decorators')
    exec(compile(ast.Module(body=[selected[name] for name in names],type_ignores=[]),str(path),'exec'),ns)
    return ns

def helpers():
    base=dict(json=json,hashlib=hashlib,math=math,random=random,struct=struct,copy=copy,
        SPAN_FIELDS=('actor','action','object','conditions','exceptions','temporal'),MAX_SOURCE_TOKENS=128,
        MAX_NEW_STEPS=32,MAX_SECONDS=32,MAX_BYTES=128*1024*1024,
        POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
        LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995')
    detach(TARGETED,('_require','_raw','checkpoint_digest','_policy','_validate_policy','_f32','_progress','_batch_indices'),base)
    targeted=SimpleNamespace(**{key:base[key] for key in ('_policy','_f32','_progress','_batch_indices')},
        SOURCE_PARENT_SHA256='a'*64,SOURCE_MODEL_SHA256='b'*64)
    ns=dict(copy=copy,hashlib=hashlib,json=json,math=math,ORIGINAL_PARAMETER_NAMES=ORIGINAL,
        FEATURE_PARAMETER_NAMES=FEATURES,SPLIT_FEATURE_PARAMETER_NAMES=SPLIT,FACET_PARAMETER_NAMES=FACETS,
        LATENT_PARAMETER_NAMES=LATENT,MODEL_PARAMETER_NAMES=NAMES,TRAINABLE_PARAMETER_NAMES=TRAINABLE,
        BRANCH_DIGEST_FIELDS=BRANCH_FIELDS,MAX_NEW_STEPS=32,MAX_SECONDS=32,MAX_BYTES=128*1024*1024,
        POLICY_SCHEMA='bounded-source-span-split-feature-policy/v1',targeted=targeted,
        _require=base['_require'],_raw=base['_raw'],checkpoint_digest=base['checkpoint_digest'],
        span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z')),
        SCHEMA='bounded-split-feature-span-legal-formula-checkpoint/v1',LINEAGE_ID='bounded_source_span_split_features_v1',
        FALSE={key:False for key in FLAGS},_implementation=lambda:{'test_producer':'c'*64},
        continuation=SimpleNamespace(_validated=lambda child:child['base_checkpoint']))
    detach(SOURCE,('_initial_state','_branch_digests','_branch_initialization','_partition','_policy','_validate_policy',
        '_state_digest','_configure_parameters','_validate_optimizer_state','_origin','_validated','_modal_rows',
        '_validate_branch_pair','_freeze_entry','_freeze_summary','_constant_entry','_constant_summary','_model'),ns)
    return ns

def checkpoint(ns,steps=0):
    config=dict(latent_dimension=384,latent_enabled=False,seed=1729,learning_rate=.001,batch_size=12)
    parent={name:[float(index)] for index,name in enumerate(ORIGINAL)}
    initial=dict(config=config,training_manifest_sha256='d'*64,tuning_manifest_sha256='e'*64,training_count=168,tuning_count=96,
        model_state=parent,optimizer_state=dict(schema='adam-default-betas-eps/v1',parameters={}),progress=dict(ZERO))
    child=dict(base_checkpoint=initial,source_parent_checkpoint_sha256='a'*64,initial_model_state_sha256='b'*64,
        source_parent_optimizer_steps=400,parent_checkpoint_sha256=None)
    policy=ns['_policy']('split-features')
    value=dict(schema=ns['SCHEMA'],lineage_id=ns['LINEAGE_ID'],implementation=ns['_implementation'](),training_policy=policy,
        training_policy_sha256=ns['checkpoint_digest'](policy),initial_training_policy_sha256=ns['checkpoint_digest'](policy),
        initial_continuation_checkpoint=child,initial_continuation_checkpoint_sha256=ns['checkpoint_digest'](child),
        source_parent_checkpoint_sha256='a'*64,source_parent_model_state_sha256='b'*64,config=copy.deepcopy(config),
        training_manifest_sha256='d'*64,tuning_manifest_sha256='e'*64,training_count=168,tuning_count=96,
        model_state=ns['_initial_state'](parent),branch_initialization=ns['_branch_initialization'](parent),
        optimizer_state=dict(schema='adam-default-betas-eps/v1',parameters={}),progress=dict(ZERO),parent_checkpoint_sha256=None,**ns['FALSE'])
    value['initial_checkpoint_sha256']=ns['checkpoint_digest'](value)
    if steps:
        value['progress']=dict(epochs_completed=steps//14,row_cursor=(steps%14)*12,optimizer_steps=steps)
        value['parent_checkpoint_sha256']='f'*64
        value['model_state']['span_encoder.weight_ih_l0']=[99.]
        value['optimizer_state']['parameters']={name:dict(step=steps,exp_avg=[0.],exp_avg_sq=[0.]) for name in TRAINABLE}
    return value

class Parameter:
    def __init__(self,value):self.value=value;self.grad='stale';self.requires_grad=True;self.storage=None
    def requires_grad_(self,flag):self.requires_grad=flag;return self
    def untyped_storage(self):return SimpleNamespace(data_ptr=lambda:id(self) if self.storage is None else self.storage)
    def detach(self):return self
    def tolist(self):return [float(self.value)]
class Model:
    def __init__(self):self.named={name:Parameter(index) for index,name in enumerate(NAMES)}
    def named_parameters(self):return iter(self.named.items())
    def state_dict(self):return self.named

def freeze_fixture(ns):
    records=[dict(id='row0',source_text='Alpha may inspect records.'),dict(id='row1',source_text='Beta shall file notices.')]
    modal=[[1.,2.,3.],[4.,5.,6.]];branches={key:str(index)*64 for index,key in enumerate(BRANCH_FIELDS,1)}
    part=ns['_partition']('split-features')
    entry=ns['_freeze_entry'](1,[1,4],records,part,'7'*64,'7'*64,['span_encoder.weight_ih_l0'],modal,copy.deepcopy(modal),branches,copy.deepcopy(branches))
    batch=dict(optimizer_step=1,indices=[1,4],ids=['row0','row1'])
    return part,entry,batch,records,modal,branches

class SplitFeatureContracts(unittest.TestCase):
    def setUp(self):self.ns=helpers()
    def test_exact34_partition17_each_with_ordered_feature_then_head_optimizer(self):
        part=self.ns['_partition']('split-features')
        self.assertEqual(len(NAMES),34);self.assertEqual(len(set(NAMES)),34)
        self.assertEqual(part['optimizer_parameter_order'],list(TRAINABLE));self.assertEqual(len(TRAINABLE),17)
        self.assertEqual(set(part['frozen_parameter_names']),set(FEATURES+ORIGINAL[11:13]+LATENT))
        self.assertFalse(part['feature_parameters_or_storage_shared'])
    def test_closed_policy_refuses_other_modes_seeds_and_loss_changes(self):
        for mode in (None,True,'all-parameters','span-heads-only','split-features '):
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.ns['_partition'](mode)
        for kwargs in (dict(seed=42),dict(batch_order_seed=True),dict(batch_size=6)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.ns['_policy']('split-features',**kwargs)
        p=self.ns['_policy']('split-features');self.ns['_validate_policy'](p)
        self.assertEqual(p['objective_policy']['presence_ce_weight'],1);self.assertEqual(p['objective_policy']['modality_loss_weight'],2)
        self.assertFalse(p['objective_policy']['actor_ranking_enabled']);self.assertTrue(p['modality_CE_is_constant'])
        p['modality_CE_span_gradient_connection']=True
        with self.assertRaises(ValueError):self.ns['_validate_policy'](p)
    def test_initial_feature_copies_parent_values_without_mutable_alias(self):
        parent={name:[float(i)] for i,name in enumerate(ORIGINAL)};state=self.ns['_initial_state'](parent)
        self.assertEqual(set(state),set(NAMES))
        for name in FEATURES:
            self.assertEqual(state[name],state['span_'+name]);self.assertIsNot(state[name],state['span_'+name])
            self.assertIsNot(parent[name],state[name])
        state['span_byte_embedding.weight'][0]+=1
        self.assertNotEqual(state['span_byte_embedding.weight'],state['byte_embedding.weight'])
        with self.assertRaises(ValueError):self.ns['_initial_state']({})
    def test_normalized_branch_hashes_separate_features_paths_and_combined_state(self):
        cp=checkpoint(self.ns);initial=cp['branch_initialization'];digests=initial['initial_branch_digests']
        self.assertEqual(digests['modality_feature_state_sha256'],digests['span_feature_state_sha256'])
        self.assertNotEqual(initial['initial_combined_model_state_sha256'],self.ns['checkpoint_digest'](cp['initial_continuation_checkpoint']['base_checkpoint']['model_state']))
        after=copy.deepcopy(cp['model_state']);after['span_encoder.bias_ih_l0']=[-10.]
        right=self.ns['_branch_digests'](after)
        for field in ('modality_feature_state_sha256','modality_path_state_sha256','dormant_latent_state_sha256'):self.assertEqual(digests[field],right[field])
        for field in ('span_feature_state_sha256','span_path_state_sha256'):self.assertNotEqual(digests[field],right[field])
        self.ns['_validate_branch_pair'](digests,right)
    def test_parameter_configuration_excludes_all_frozen_and_rejects_identity_storage_aliases(self):
        part=self.ns['_partition']('split-features');m=Model();named,selected=self.ns['_configure_parameters'](m,part)
        self.assertEqual([id(x) for x in selected],[id(named[n]) for n in TRAINABLE])
        self.assertTrue(all(x.grad is None and x.requires_grad==(n in TRAINABLE) for n,x in named.items()))
        for kind in ('Parameter','storage','order','extra'):
            m=Model()
            if kind=='Parameter':m.named[SPLIT[0]]=m.named[FEATURES[0]]
            elif kind=='storage':m.named[SPLIT[0]].storage=m.named[FEATURES[0]].untyped_storage().data_ptr()
            elif kind=='order':m.named=dict(reversed(list(m.named.items())))
            else:m.named['unknown.weight']=Parameter(0)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.ns['_configure_parameters'](m,part)
    def test_subset_moments_exact_no_frozen_or_fabricated_old_state(self):
        part=self.ns['_partition']('split-features')
        for steps in (0,1,14,32):self.ns['_validate_optimizer_state'](checkpoint(self.ns,steps)['optimizer_state'],part,steps)
        for kind in ('missing','frozen','bool_step','stale'):
            moments=checkpoint(self.ns,1)['optimizer_state']
            if kind=='missing':moments['parameters'].pop(TRAINABLE[0])
            elif kind=='frozen':moments['parameters'][FEATURES[0]]=dict(step=1,exp_avg=[0.],exp_avg_sq=[0.])
            else:moments['parameters'][TRAINABLE[0]]['step']=True if kind=='bool_step' else 0
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.ns['_validate_optimizer_state'](moments,part,1)
    def test_outer_initial_and_trained_live_branches_validate(self):
        for steps in (0,1,14,32):
            with self.subTest(steps=steps):self.ns['_validated'](checkpoint(self.ns,steps))
    def test_outer_rejects_frozen_and_initial_branch_provenance_mutations(self):
        for name in FEATURES+ORIGINAL[11:13]+LATENT:
            cp=checkpoint(self.ns,1);cp['model_state'][name]=[-100.]
            with self.subTest(name=name),self.assertRaises(ValueError):self.ns['_validated'](cp)
        for field in ('parent_parameter_source_map','initial_combined_model_state_sha256','initial_branch_digests'):
            cp=checkpoint(self.ns,1);cp['branch_initialization'][field]={}
            with self.subTest(field=field),self.assertRaises(ValueError):self.ns['_validated'](cp)
    def test_outer_refuses_initial_duplicate_drift_new_loss_oldschema_or_authority(self):
        for fault in ('initial_span','objective','schema','authority','extra'):
            cp=checkpoint(self.ns)
            if fault=='initial_span':cp['model_state'][SPLIT[0]]=[-10.]
            elif fault=='objective':cp['training_policy']['objective_policy']['presence_ce_weight']=2
            elif fault=='schema':cp['schema']='bounded-permission-retention-span-legal-formula-checkpoint/v1'
            elif fault=='authority':cp['formalized']=True
            else:cp['unknown']=1
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.ns['_validated'](cp)
    def test_frozen_digest_excludes_trainable_branch_changes(self):
        m=Model();part=self.ns['_partition']('split-features');old=self.ns['_state_digest'](m,part['frozen_parameter_names'])
        m.named[SPLIT[0]].value+=1;self.assertEqual(old,self.ns['_state_digest'](m,part['frozen_parameter_names']))
        m.named[FEATURES[0]].value+=1;self.assertNotEqual(old,self.ns['_state_digest'](m,part['frozen_parameter_names']))
    def test_completed_freeze_trace_joins_normalized_paths_and_modal_scores(self):
        part,entry,batch,_,_,_=freeze_fixture(self.ns);summary=self.ns['_freeze_summary']([entry],[batch],part)
        self.assertEqual(summary['completed_updates'],1);self.assertFalse(summary['independent_tensor_custody_attested'])
        mutations={
            'frozen_digest':lambda e:e.update(frozen_parameters_sha256_after='8'*64),
            'frozen_name':lambda e:e.update(changed_parameter_names=['encoder.bias_ih_l0']),
            'modal':lambda e:e['modality_after'][0]['modality_logits'].__setitem__(0,4.),
            'branch':lambda e:e['branch_digests_after'].__setitem__('modality_path_state_sha256','9'*64),
            'gradient':lambda e:e.update(frozen_gradients_none_before_and_after=False),
            'step':lambda e:e.update(optimizer_step=2),'ids':lambda e:e.update(ids=['wrong','row1']),
            'authority':lambda e:e.update(qualified=True)}
        for label,mutate in mutations.items():
            broken=copy.deepcopy(entry);mutate(broken)
            with self.subTest(label=label),self.assertRaises(ValueError):self.ns['_freeze_summary']([broken],[batch],part)
    def test_branch_trace_rejects_noncontinuous_live_span_states(self):
        part,entry,batch,_,_,_=freeze_fixture(self.ns)
        second=copy.deepcopy(entry);second['optimizer_step']=2;second['branch_digests_before']['span_feature_state_sha256']='9'*64
        second['branch_digests_after']['span_feature_state_sha256']='9'*64
        with self.assertRaises(ValueError):self.ns['_freeze_summary']([entry,second],[batch,dict(batch,optimizer_step=2)],part)
    def test_constant_modality_component_and_zero_gradient_connection_are_closed(self):
        entry=self.ns['_constant_entry'](1,[0],['id0'],2.,.5);batch=dict(optimizer_step=1,indices=[0],ids=['id0'])
        self.ns['_constant_summary']([entry],[batch])
        for field,value in (('modality_CE',math.inf),('total_loss_constant_contribution',.25),('span_path_gradient_connection',True),('extra_source_model_forwards',1),('ids',['wrong'])):
            broken=copy.deepcopy(entry);broken[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.ns['_constant_summary']([broken],[batch])
    def test_model_factory_copies_features_without_random_draw_and_routes_heads(self):
        class Module:
            def __init__(self):pass
        class Value:
            def __init__(self,label):self.label=label
            def clone(self):return Value(self.label)
            def __getitem__(self,key):return self
            def __mul__(self,other):return self
            def __truediv__(self,other):return self
            def __invert__(self):return self
            def sum(self,*a,**k):return self
            def reshape(self,*a):return self
            def transpose(self,*a):return self
            def masked_fill(self,*a):return self
        class Part:
            def __init__(self,name):self.name=name;self.parameters={n:Parameter(i) for i,n in enumerate(ORIGINAL) if n.startswith(name+'.')}
            def __call__(self,value):return Value(self.name+':'+value.label)
        names=('byte_embedding','token_projection','encoder','modality','presence','start','end','latent_down','latent_up')
        parent=SimpleNamespace(**{name:Part(name) for name in names});calls=[];rng=Value('stable')
        class NoGrad:
            def __enter__(self):calls.append('no_grad')
            def __exit__(self,*args):return False
        torch=SimpleNamespace(nn=SimpleNamespace(Module=Module),get_rng_state=lambda:rng,equal=lambda a,b:a.label==b.label,no_grad=NoGrad)
        self.ns['span']._model=lambda *args:parent
        model=self.ns['_model'](torch,{})
        for field in ('byte_embedding','token_projection','encoder'):
            original=getattr(model,field);duplicate=getattr(model,'span_'+field)
            self.assertIsNot(original,duplicate)
            self.assertEqual({n:p.value for n,p in original.parameters.items()},{n:p.value for n,p in duplicate.parameters.items()})
            self.assertTrue(all(id(original.parameters[n])!=id(duplicate.parameters[n]) for n in original.parameters))
        def features(*args):
            calls.append('span' if args[-1] else 'modality');return Value('span' if args[-1] else 'modality'),Value('mask')
        model._features=features
        output=model.forward(None,None,Value('lengths'),None)
        self.assertEqual(output['modality'].label,'modality:modality')
        for name in ('presence','start','end'):self.assertEqual(output[name].label,name+':span')
        self.assertEqual(calls,['no_grad','modality','span'])
    def test_source_closure_preserves_old_producers_and_exposes_honest_forward_counts(self):
        tree=ast.parse(SOURCE.read_bytes());text=SOURCE.read_text()
        top_imports=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any(any(a.name in ('torch','numpy','transformers','datasets') for a in n.names) for n in top_imports))
        self.assertEqual(sum(isinstance(n,ast.Import) and any(a.name=='torch' for a in n.names) for n in ast.walk(tree)),1)
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign):self.assertFalse(any(isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name)
                and t.value.id in ('span','targeted','continuation') for t in node.targets))
        self.assertIn('loss, objective = targeted._loss(torch, lambda *_: output',text)
        self.assertIn('output["modality"].requires_grad is False',text)
        self.assertIn('training_span_encoder_calls',text);self.assertIn('span_encoder_forwards',text)
        self.assertIn('torch.equal(ambient, torch.get_rng_state())',text)

if __name__=='__main__':unittest.main()

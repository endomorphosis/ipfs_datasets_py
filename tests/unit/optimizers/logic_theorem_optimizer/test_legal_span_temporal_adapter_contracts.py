"""Exact-source contracts with inert owners; never import a numerical producer."""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[4] / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_adapter.py"
SPLIT = SOURCE.with_name("legal_span_split_features.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def deny_import(name, *args, **kwargs):
    raise AssertionError("Detached contracts cannot import: " + name)


def owner_namespace():
    previous = {}
    selected = {"ORIGINAL_PARAMETER_NAMES", "FEATURE_PARAMETER_NAMES", "SPLIT_FEATURE_PARAMETER_NAMES", "LATENT_PARAMETER_NAMES", "MODEL_PARAMETER_NAMES"}
    for node in ast.parse(SPLIT.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in selected for t in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPLIT)+"#constants", "exec"), previous)
    names = previous["MODEL_PARAMETER_NAMES"]
    span = SimpleNamespace(FALSE=dict.fromkeys(("admitted", "formalized", "promotion_performed", "proof_authority", "publication_performed", "qualified", "roundtrip_ok", "semantic_correctness_verified"), False),
        _require=require, _raw=raw, checkpoint_digest=digest, _SHA=re.compile(r"[0-9a-f]{64}"),
        OPTIONAL_FIELDS=("object", "conditions", "exceptions", "temporal"),
        SPAN_FIELDS=("actor", "action", "object", "conditions", "exceptions", "temporal"), _implementation=lambda:{"inert":"span"})
    def progress(p):
        require(type(p) is dict and set(p)=={"optimizer_steps","epochs_completed","row_cursor"}
            and all(type(v) is int and v>=0 for v in p.values()), "progress")
        return dict(p)
    def batch_indices(count,p,batch_size,seed):
        p=progress(p);require(p['row_cursor']<count and p['row_cursor']%batch_size==0
            and p['optimizer_steps']==p['epochs_completed']*14+p['row_cursor']//batch_size,"cursor")
        return list(range(p['row_cursor'],p['row_cursor']+batch_size))
    def bounded(rows,tuning):
        require(len(rows)==168 and not tuning,"training only")
        return [dict(id=r['id'],source_text=r['source_text'],labels=dict(presence=[True,True,False,False,False,r['temporal']])) for r in rows],[]
    def base_diagnostic(value):
        require(value=={'total_loss':2.},'inert base diagnostic')
    targeted = SimpleNamespace(MAX_BYTES=64*1024*1024, LEGACY96_SHA256='d'*64,
        _policy=lambda seed,**kw:dict(seed=seed,**kw), _implementation=lambda:{"inert":"targeted"},
        _progress=progress,_batch_indices=batch_indices,_bounded_splits=bounded,
        _validate_objective_diagnostics=base_diagnostic)
    split = SimpleNamespace(MODEL_PARAMETER_NAMES=names,_implementation=lambda:{"inert":"split"},
        _validated=lambda s:require(set(s['model_state'])==set(names),'source34'),
        _branch_digests=lambda state:dict.fromkeys(('modality_feature_state_sha256','span_feature_state_sha256',
            'modality_path_state_sha256','span_path_state_sha256','dormant_latent_state_sha256'),digest(state)))
    continuation=SimpleNamespace(_implementation=lambda:{"inert":"continuation"},_context_contract=lambda c:copy.deepcopy(c))
    namespace=dict(__file__=str(SOURCE),__name__='inert_temporal_adapter',copy=copy,hashlib=hashlib,json=json,
        math=math,Path=Path,split=split,targeted=targeted,continuation=continuation,span=span)
    # Strip all imports, including future imports. All numerical import paths
    # remain uncallable; class methods/functions are merely defined here.
    tree=ast.parse(SOURCE.read_bytes())
    body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    namespace['__builtins__']=dict(vars(__import__('builtins')),__import__=deny_import)
    exec(compile(ast.Module(body=body,type_ignores=[]),str(SOURCE)+'#inert-owner-execution','exec'),namespace)
    return namespace


def fixture(ns,objective='temporal-ce-control'):
    state={name:[[float(i)]] for i,name in enumerate(ns['BASE_PARAMETER_NAMES'])}
    state['presence.weight']=[[float(i),float(i+1)] for i in range(8)]
    state['presence.bias']=[float(i)/10 for i in range(8)]
    rows=[dict(id='train-'+str(i),source_text='source '+str(i),temporal=(i%2==0)) for i in range(168)]
    context=dict(mode='source-only',dimension=384)
    child=dict(context_contract=context,context_contract_sha256=digest(context))
    source=dict(model_state=state,progress=dict(optimizer_steps=32),config=dict(hidden_size=1,latent_dimension=384,latent_enabled=False),
        initial_continuation_checkpoint=child,training_manifest_sha256=digest(rows),source_parent_checkpoint_sha256='a'*64,
        source_parent_model_state_sha256='b'*64)
    # Real immutable constants are checked separately. These substitutions let
    # the actual closed provenance predicates inspect an inert synthetic state.
    ns['SOURCE_SPLIT_SHA256']=digest(source);ns['SOURCE_SPLIT_MODEL_SHA256']=digest(state)
    checkpoint=ns['build_checkpoint'](source,rows,(),context_contract=context,objective=objective)
    return source,rows,checkpoint


class Scalar:
    def __init__(self,value,gradient=0.):self.value=float(value);self.gradient=float(gradient)
    def __float__(self):return self.value
    def detach(self):return self
    def __add__(self,other):
        other=other if isinstance(other,Scalar) else Scalar(other)
        return Scalar(self.value+other.value,self.gradient+other.gradient)
    __radd__=__add__
    def __neg__(self):return Scalar(-self.value,-self.gradient)
    def __sub__(self,other):return self+-other if isinstance(other,Scalar) else self+(-other)
    def __rsub__(self,other):return other+-self
    def __mul__(self,other):
        other=other if isinstance(other,Scalar) else Scalar(other)
        return Scalar(self.value*other.value,self.gradient*other.value+self.value*other.gradient)
    __rmul__=__mul__
    def __truediv__(self,other):return self*(1/other)


class Vector:
    def __init__(self,values):self.values=values
    def __getitem__(self,index):return self.values[index]
    def __sub__(self,other):return Vector([a-b for a,b in zip(self.values,other.values,strict=True)])
    def mean(self):return sum(self.values,Scalar(0.))/len(self.values)


class Presence:
    def __init__(self,margins):self.margins=margins
    def __getitem__(self,index):
        row,role,*choice=index;assert role==3
        if isinstance(row,slice):return Vector([v if choice[0]==1 else Scalar(0.) for v in self.margins])
        return [Scalar(0.),self.margins[row]]


class Bits:
    def __init__(self,values):self.values=values
    def all(self):return all(self.values)


class Array:
    def __init__(self,values):self.values=values
    def __getitem__(self,index):return Array(self.values[index])
    def flat(self):
        return [v for row in self.values for v in row] if self.values and isinstance(self.values[0],list) else self.values
    def isfinite(self):return Bits([math.isfinite(v) for v in self.flat()])
    def __eq__(self,other):return Bits([v==other for v in self.flat()])


class Parameter:
    def __init__(self,pointer):self.pointer=pointer;self.grad='unconfigured';self.requires_grad=None
    def untyped_storage(self):return SimpleNamespace(data_ptr=lambda:self.pointer)
    def requires_grad_(self,value):self.requires_grad=value


class TemporalAdapterContracts(unittest.TestCase):
    def setUp(self):self.ns=owner_namespace()
    def test_real_source_constants_and_closed_partition(self):
        ns=self.ns
        self.assertEqual(ns['SOURCE_SPLIT_SHA256'],'95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035')
        self.assertEqual(ns['SOURCE_SPLIT_MODEL_SHA256'],'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5')
        part=ns['_partition']();self.assertEqual(len(part['model_parameter_names']),36)
        self.assertEqual(len(part['frozen_parameter_names']),34)
        self.assertEqual(part['optimizer_parameter_order'],['temporal_presence.weight','temporal_presence.bias'])
        self.assertEqual(part['inactive_head_rows'],list(range(6)))
    def test_deep_initialization_and_inactive_rows(self):
        ns=self.ns;source,rows,c=fixture(ns);state=ns['_initial_state'](source['model_state'])
        state['temporal_presence.weight'][0][0]=999
        self.assertNotEqual(state['temporal_presence.weight'][0][0],source['model_state']['presence.weight'][0][0])
        self.assertNotEqual(state['temporal_presence.weight'][0][0],state['presence.weight'][0][0])
        self.assertEqual(len(ns['_inactive_state'](c['model_state'])['temporal_presence.bias']),6)
        for malformed in ({},dict(source['model_state'],extra=[0.])):
            with self.subTest(malformed=bool(malformed)),self.assertRaises(ValueError):ns['_initial_state'](malformed)
    def test_fixed_policies_and_mutations(self):
        ns=self.ns
        for cell in ns['OBJECTIVES']:
            policy=ns['_policy'](cell);self.assertEqual(ns['_validate_policy'](policy),policy)
            self.assertEqual(policy['anchor_factors'],dict(legacy_positive=7/4,authored_negative=7/3))
            for key,value in [('margin',2.),('margin_batch_denominator','eligible_only'),('evaluation_references_used',True)]:
                p=copy.deepcopy(policy);p[key]=value
                with self.subTest(cell=cell,key=key),self.assertRaises(ValueError):ns['_validate_policy'](p)
            p=copy.deepcopy(policy);p['optimizer']['weight_decay']=.01
            with self.assertRaises(ValueError):ns['_validate_policy'](p)
        for kwargs in [dict(objective='unknown'),dict(objective=ns['OBJECTIVES'][0],seed=True),dict(objective=ns['OBJECTIVES'][0],batch_size=13)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ns['_policy'](**kwargs)
    def test_source_and_training_provenance(self):
        ns=self.ns;source,rows,c=fixture(ns);ns['_validated'](c)
        for mutate in [lambda c:c.update(source_split_checkpoint_sha256='e'*64),lambda c:c.update(training_manifest_sha256='e'*64),
            lambda c:c.update(legacy_prefix_sha256='e'*64),lambda c:c.update(tuning_count=96),
            lambda c:c['source_split_checkpoint']['progress'].update(optimizer_steps=31),lambda c:c.update(extra=True),
            lambda c:c['config'].update(latent_enabled=True),lambda c:c.update(source_split_optimizer_steps=400)]:
            bad=copy.deepcopy(c);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):ns['_validated'](bad)
        with self.assertRaises(ValueError):ns['build_checkpoint'](source,list(reversed(rows)),(),context_contract=c['context_contract'])
        with self.assertRaises(ValueError):ns['build_checkpoint'](source,rows,[dict(reference=True)],context_contract=c['context_contract'])
        with self.assertRaises(ValueError):ns['build_checkpoint'](source,rows,(),context_contract=dict(wrong=True))
    def test_frozen_state_inactive_rows_and_live_lineage(self):
        ns=self.ns;_,_,c=fixture(ns)
        for name in [ns['BASE_PARAMETER_NAMES'][0],'presence.bias','temporal_presence.bias']:
            bad=copy.deepcopy(c)
            if name=='temporal_presence.bias':bad['model_state'][name][0]+=1
            elif name=='presence.bias':bad['model_state'][name][7]+=1
            else:bad['model_state'][name][0][0]+=1
            with self.subTest(name=name),self.assertRaises(ValueError):ns['_validated'](bad)
        bad=copy.deepcopy(c);bad['model_state']['temporal_presence.bias'][7]+=1
        with self.assertRaises(ValueError):ns['_validated'](bad)
        bad['parent_checkpoint_sha256']=digest(c);bad['progress']=dict(optimizer_steps=1,epochs_completed=0,row_cursor=12)
        bad['optimizer_state']=dict(schema='adam-default-betas-eps/v1',parameters={name:dict(step=1,exp_avg=[[0.] for _ in range(8)],exp_avg_sq=[[0.] for _ in range(8)]) for name in ns['TRAINABLE_PARAMETER_NAMES']})
        ns['_validated'](bad)
        self.assertEqual(ns['_origin'](bad)['model_state'],c['model_state'])
    def test_optimizer_actual_subset_and_inactive_moments(self):
        ns=self.ns;empty=dict(schema='adam-default-betas-eps/v1',parameters={});ns['_validate_optimizer_state'](empty,0)
        state=dict(schema=empty['schema'],parameters={name:dict(step=1,exp_avg=[0.]*8,exp_avg_sq=[0.]*8) for name in ns['TRAINABLE_PARAMETER_NAMES']})
        ns['_validate_optimizer_state'](state,1)
        for mutate in [lambda s:s['parameters'].pop('temporal_presence.bias'),lambda s:s['parameters'].update({'presence.weight':s['parameters']['temporal_presence.weight']}),
            lambda s:s['parameters']['temporal_presence.weight'].update(step=2),lambda s:s['parameters']['temporal_presence.bias']['exp_avg'].__setitem__(0,.1),
            lambda s:s['parameters']['temporal_presence.bias']['exp_avg_sq'].__setitem__(5,.1)]:
            bad=copy.deepcopy(state);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):ns['_validate_optimizer_state'](bad,1)
        with self.assertRaises(ValueError):ns['_validate_optimizer_state'](state,0)
    def test_parameter_and_storage_alias_denial(self):
        ns=self.ns;names=ns['MODEL_PARAMETER_NAMES'];params={name:Parameter(i+1) for i,name in enumerate(names)}
        named,selected=ns['_configure_parameters'](SimpleNamespace(named_parameters=lambda:list(params.items())))
        self.assertEqual(selected,[params[n] for n in ns['TRAINABLE_PARAMETER_NAMES']])
        self.assertTrue(all(p.grad is None for p in named.values()))
        self.assertEqual(sum(p.requires_grad for p in named.values()),2)
        for shared in ('parameter','storage','order'):
            bad=dict(params)
            if shared=='parameter':bad[names[-1]]=bad[names[0]]
            elif shared=='storage':bad[names[-1]]=Parameter(1)
            else:bad=dict(reversed(list(bad.items())))
            with self.subTest(shared=shared),self.assertRaises(ValueError):ns['_configure_parameters'](SimpleNamespace(named_parameters=lambda:list(bad.items())))
    def test_gradient_none_zero_rows_and_moments(self):
        ns=self.ns;named={n:Parameter(i) for i,n in enumerate(ns['MODEL_PARAMETER_NAMES'])}
        for n,p in named.items():p.grad=None if n in ns['BASE_PARAMETER_NAMES'] else Array([0.]*6+[1.,-1.])
        optimizer=SimpleNamespace(state={named[n]:dict(exp_avg=Array([0.]*8),exp_avg_sq=Array([0.]*8)) for n in ns['TRAINABLE_PARAMETER_NAMES']})
        ns['_row_invariants'](named,optimizer)
        named[ns['BASE_PARAMETER_NAMES'][0]].grad=Array([0.]*8)
        with self.assertRaises(ValueError):ns['_row_invariants'](named,optimizer)
        named[ns['BASE_PARAMETER_NAMES'][0]].grad=None
        p=named['temporal_presence.bias'];p.grad=Array([.1]+[0.]*5+[1.,-1.])
        with self.assertRaises(ValueError):ns['_row_invariants'](named,optimizer)
        p.grad=Array([0.]*6+[1.,-1.]);optimizer.state[p]['exp_avg']=Array([.1]+[0.]*7)
        with self.assertRaises(ValueError):ns['_row_invariants'](named,optimizer)
    def test_training_strata_and_labels(self):
        ns=self.ns;_,rows,_=fixture(ns);self.assertEqual(len(ns['_training_records'](rows)),168)
        self.assertEqual(ns['_stratum'](95,True),'legacy_positive');self.assertEqual(ns['_stratum'](96,False),'authored_negative')
        for index,present in [(True,True),(168,True),(-1,False),(1,1)]:
            with self.subTest(index=index,present=present),self.assertRaises(ValueError):ns['_stratum'](index,present)
        bad=copy.deepcopy(rows);bad[0]['temporal']=not bad[0]['temporal']
        with self.assertRaises(ValueError):ns['_training_records'](bad)
        original=ns['span'].OPTIONAL_FIELDS;ns['span'].OPTIONAL_FIELDS=tuple(reversed(original))
        with self.assertRaises(ValueError):ns['_training_records'](rows)
    def loss_fixture(self,indices,targets,margins,cell):
        ns=self.ns
        def ce(logits,target):return Scalar(math.log1p(math.exp(-float(logits[1]) if target else float(logits[1]))))
        fake=SimpleNamespace(relu=lambda s:Scalar(max(0,s.value),s.gradient if s.value>0 else 0.),stack=lambda x:Vector(x),
            tensor=lambda value,**kw:value,long='inert-long',nn=SimpleNamespace(functional=SimpleNamespace(cross_entropy=ce)))
        ns['targeted']._loss=lambda *args:(Scalar(2.),dict(total_loss=2.))
        records=[dict(id='train-'+str(i),labels=dict(presence=[True,True,False,False,False,t])) for i,t in zip(indices,targets,strict=True)]
        return ns['_loss'](fake,dict(presence=Presence([Scalar(v,1.) for v in margins])),records,indices,ns['_policy'](cell))
    def test_signed_margin_and_all_batch_normalization(self):
        loss,d=self.loss_fixture([0,96,1,97],[True,False,False,True],[0.,0.,0.,0.],'temporal-anchor-margin')
        expected=(7/4+7/3)/4
        self.assertAlmostEqual(d['balanced_margin'],expected);self.assertAlmostEqual(float(loss),2+.5*expected/8)
        self.assertAlmostEqual(loss.gradient,.5*(-7/4+7/3)/4/8)
        self.assertEqual([r['anchor_factor'] for r in d['rows']],[7/4,7/3,0.,0.])
    def test_missing_groups_differentiable_zero_and_control(self):
        loss,d=self.loss_fixture([1,97],[False,True],[.25,-.5],'temporal-anchor-margin')
        self.assertEqual(d['balanced_margin'],0.);self.assertEqual(float(loss),2.);self.assertEqual(loss.gradient,0.)
        loss,d=self.loss_fixture([0,1],[True,False],[0.,0.],'temporal-anchor-margin')
        self.assertEqual(d['balanced_margin'],7/8)
        loss,d=self.loss_fixture([0,96],[True,False],[0.,0.],'temporal-ce-control')
        self.assertEqual(float(loss),2.);self.assertEqual(loss.gradient,0.);self.assertEqual(d['weighted_margin_contribution'],0.)
        loss,d=self.loss_fixture([0,96],[True,False],[2.,-2.],'temporal-anchor-margin')
        self.assertEqual(d['balanced_margin'],0.)
    def test_objective_trace_recomposition_and_mutations(self):
        ns=self.ns;loss,d=self.loss_fixture([0,96],[True,False],[0.,0.],'temporal-anchor-margin')
        entry=dict(optimizer_step=1,indices=[0,96],ids=['train-0','train-96'],details=d);batch=dict(optimizer_step=1,indices=[0,96],ids=entry['ids'],loss=float(loss));policy=ns['_policy']('temporal-anchor-margin')
        ns['_validate_objective_entry'](entry,batch,policy)
        for mutate in [lambda e:e['details'].update(batch_denominator=1),lambda e:e['details'].update(evaluation_references_used=True),
            lambda e:e['details'].update(total_loss=9.),lambda e:e['details']['rows'][0].update(stratum='authored_positive'),
            lambda e:e['details']['rows'][1].update(anchor_factor=1.),lambda e:e['details']['rows'][0].update(hinge=9.),
            lambda e:e['details']['rows'][0].update(temporal_CE=float('nan')),lambda e:e.update(ids=['other','train-96'])]:
            bad=copy.deepcopy(entry);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):ns['_validate_objective_entry'](bad,batch,policy)
    def test_freeze_trace_binds_base_rows_heads_and_update(self):
        ns=self.ns;_,_,c=fixture(ns);branches=ns['_branch_digests'](c['model_state'])
        batch=dict(optimizer_step=1,indices=[0],ids=['train-0'])
        entry=dict(**batch,frozen_before=ns['SOURCE_SPLIT_MODEL_SHA256'],frozen_after=ns['SOURCE_SPLIT_MODEL_SHA256'],inactive_before=branches['inactive_temporal_head_rows_sha256'],inactive_after=branches['inactive_temporal_head_rows_sha256'],frozen_head_sample_sha256='a'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,inactive_moments_zero=True,changed_parameter_names=['temporal_presence.bias'],completed_returned_update=True,branch_digests_before=branches,branch_digests_after=copy.deepcopy(branches))
        ns['_validate_freeze_entry'](entry,batch)
        for mutate in [lambda e:e.update(frozen_after='e'*64),lambda e:e.update(inactive_after='e'*64),lambda e:e.update(inactive_moments_zero=False),
            lambda e:e.update(changed_parameter_names=['presence.bias']),lambda e:e['branch_digests_after'].update(span_path_state_sha256='e'*64),lambda e:e.update(optimizer_step=2)]:
            bad=copy.deepcopy(entry);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):ns['_validate_freeze_entry'](bad,batch)
    def test_model_source_routes_learned_pool_without_third_encoder_or_hooks(self):
        tree=ast.parse(SOURCE.read_bytes());model=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_model');text=ast.unparse(model)
        self.assertIn('class TemporalAdapter(type(base))',text);self.assertIn('base.__class__ = TemporalAdapter',text)
        self.assertIn('copy.deepcopy(base.presence)',text);self.assertIn('self.temporal_presence(pooled)',text)
        self.assertIn('old_presence[:, :3, :]',text);self.assertIn('[:, 3:4, :]',text)
        self.assertEqual(len([n for n in ast.walk(model) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_features']),2)
        self.assertNotIn('register_',text);self.assertNotIn('manual_seed',text)
        restore=ast.unparse(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_restore'))
        self.assertIn('weight_decay=0.0',restore);self.assertIn('foreach=False',restore)
        train=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='train_decoder')
        self.assertEqual(len([n for n in ast.walk(train) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='model']),1)
    def test_168_capture_bound_and_per_source128_token_bound(self):
        tree=ast.parse(SOURCE.read_bytes());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SpanTemporalPresenceAdapterDecoder')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='decode_formal_logic')
        condition=method.body[0].value.args[0]
        compiled=compile(ast.Expression(condition),str(SOURCE)+'#capture-bound','eval')
        span=SimpleNamespace(tokenize_source=lambda text:[None]*int(text))
        self.assertTrue(eval(compiled,dict(texts=['128']*168,span=span)))
        for texts in [[],['1']*169,['129'],[1]]:
            with self.subTest(count=len(texts)):self.assertFalse(eval(compiled,dict(texts=texts,span=span)))
    def test_numerical_imports_are_unavailable(self):
        with self.assertRaises(AssertionError):self.ns['_restore']({})


if __name__ == '__main__':
    unittest.main()

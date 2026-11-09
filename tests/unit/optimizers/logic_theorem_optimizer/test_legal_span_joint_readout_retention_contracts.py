"""Detached stdlib controls; never import production packages or numerical owners."""
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

SOURCE = Path(__file__).resolve().parents[4] / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_joint_readout_retention.py'

def require(value, message):
    if not value: raise ValueError(message)

def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()

def digest(value): return hashlib.sha256(raw(value)).hexdigest()

def deny(name, *args, **kwargs): raise AssertionError('numerical/production import refused: ' + name)

def namespace():
    # Reuse the existing detached dependency stubs, never import their module.
    oldtest = Path(__file__).with_name('test_legal_span_actor_context_ranking_contracts.py')
    helpers = [n for n in ast.parse(oldtest.read_bytes()).body if isinstance(n, ast.FunctionDef)
        and n.name in {'require', 'raw', 'digest', 'deny', 'selected', 'namespace'}]
    oldenv = dict(ast=ast, builtins=builtins, copy=copy, hashlib=hashlib, json=json, math=math,
        Path=Path, random=random, re=re, struct=struct, SimpleNamespace=SimpleNamespace,
        SOURCE=SOURCE.with_name('legal_span_actor_context_ranking.py'))
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(oldtest) + '#detached-stubs', 'exec'), oldenv)
    old = oldenv['namespace']()
    n = {k: old[k] for k in ('copy', 'hashlib', 'json', 'math', 'Path', 'features', 'conditions', 'refinement', 'targeted', 'continuation', 'span')}
    n.update(__file__=str(SOURCE), ranking=SimpleNamespace(**old), __builtins__=dict(vars(builtins), __import__=deny))
    nodes = [x for x in ast.parse(SOURCE.read_bytes()).body if isinstance(x, (ast.Assign, ast.FunctionDef))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE) + '#detached', 'exec'), n)
    n['old_namespace'] = old
    n['span'].tokenize_source = lambda text: [dict(text=m.group(), start=m.start(), end=m.end(),
        byte_ids=[b + 1 for b in m.group().encode()]) for m in re.finditer(r'\w+|[^\w\s]', text)]
    return n

def fixture(n):
    state = {name: [float(i)] for i, name in enumerate(n['MODEL_PARAMETER_NAMES'])}
    for name, shape in n['_trainable_shapes']().items():
        state[name] = [[(r + 1) / 8.] * shape[1] for r in range(shape[0])] if len(shape) == 2 else [.25] * shape[0]
    for name in ('conditions_presence.weight', 'conditions_presence.bias'):
        state[name] = [[.375] * 64 for _ in range(8)] if name.endswith('weight') else [.375] * 8
    rows = [dict(id='synthetic-' + str(i), source_text='actor acts target', fixture_labels=dict(modality=0,
        presence=[True, True, False, bool(i % 2), False, False],
        spans=[(0, 0), (1, 1), (-100, -100), (2, 2) if i % 2 else (-100, -100), (-100, -100), (-100, -100)])) for i in range(168)]
    def bounded(examples, tuning):
        require(len(examples) == 168 and not tuning, 'synthetic training168 only')
        return [dict(id=r['id'], source_text=r['source_text'], tokens=n['span'].tokenize_source(r['source_text']),
            labels=copy.deepcopy(r['fixture_labels'])) for r in examples], []
    n['targeted']._bounded_splits = bounded
    contract = dict(mode='source-only', dimension=384)
    child = dict(context_contract=contract, context_contract_sha256=digest(contract))
    parent = dict(model_state=state, progress=dict(optimizer_steps=32), training_manifest_sha256=digest(rows),
        config=dict(hidden_size=32, latent_dimension=384, latent_enabled=False), initial_continuation_checkpoint=child,
        source_parent_checkpoint_sha256='a' * 64, source_parent_model_state_sha256='b' * 64)
    old = n['old_namespace'];parent['source_frozen36_state_sha256'] = digest({k: state[k] for k in old['BASE_PARAMETER_NAMES']})
    old['SOURCE_ACTOR_REFINEMENT_SHA256'] = n['SOURCE_ACTOR_REFINEMENT_SHA256'] = digest(parent)
    old['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256'] = n['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256'] = digest(state)
    old['SOURCE_FROZEN36_SHA256'] = parent['source_frozen36_state_sha256']
    tokens = [{k: t[k] for k in ('text', 'start', 'end')} for t in n['span'].tokenize_source(rows[0]['source_text'])]
    scores = dict(schema='joint-source-span-scores/v1', tokens=tokens, modality_logits=[0., 0., 0.],
        presence_logits={k: [0., 1.] for k in n['span'].OPTIONAL_FIELDS},
        start_logits={k: [3., 1., 0.] for k in n['span'].SPAN_FIELDS}, end_logits={k: [3., 1., 0.] for k in n['span'].SPAN_FIELDS})
    scores['start_logits']['conditions'] = [1., 3., 2.];scores['end_logits']['conditions'] = [-1., 0., 2.]
    capture = dict(schema='actor-refinement-adapter-target-free-head-capture/v1',
        inference=dict(checkpoint_sha256=digest(parent), model_state_sha256=digest(state), target_access=False, teacher_forcing=False),
        target_access=False, teacher_forcing=False, extra_capture_forwards=0, actual_source_forwards=168,
        occurrences=[dict(id=r['id'], source_sha256=hashlib.sha256(r['source_text'].encode()).hexdigest(), scores=copy.deepcopy(scores)) for r in rows])
    teacher_raw = raw(capture);n['TEACHER_CAPTURE_BYTES'] = len(teacher_raw);n['TEACHER_CAPTURE_SHA256'] = hashlib.sha256(teacher_raw).hexdigest()
    cp = n['build_checkpoint'](parent, rows, context_contract=contract, teacher_training_capture=teacher_raw)
    return parent, rows, teacher_raw, cp

class Contracts(unittest.TestCase):
    def setUp(self): self.n = namespace()

    def test_exact_recipe_real_donor_and_teacher_pins_closed14_order(self):
        n = self.n;p = n['_policy']('joint-readout-retention-hinge');n['_validate_policy'](p)
        self.assertEqual(n['SOURCE_ACTOR_REFINEMENT_SHA256'], 'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
        self.assertEqual(n['TEACHER_CAPTURE_SHA256'], '221fa2ec37fc41298f787d4dfef1d4daf60b07c4c565a1194d2097e7c538fff1')
        self.assertEqual(n['TEACHER_CAPTURE_BYTES'], 3594328)
        self.assertEqual(n['TRAINABLE_PARAMETER_NAMES'], ('actor_start.weight', 'actor_start.bias', 'actor_end.weight', 'actor_end.bias',
            'actor_attention.query', 'actor_context.gate', 'modality.weight', 'modality.bias', 'start.weight', 'start.bias',
            'end.weight', 'end.bias', 'presence.weight', 'presence.bias'))
        part = p['parameter_partition'];self.assertEqual((len(n['MODEL_PARAMETER_NAMES']), len(n['BASE_PARAMETER_NAMES'])), (42, 28))
        self.assertEqual((part['stored_trainable_scalar_count'], part['active_trainable_scalar_count'], part['inactive_stored_scalar_count']), (2403, 713, 1690))
        self.assertEqual(sum(math.prod(s) for s in n['_trainable_shapes']().values()), 2403)
        self.assertTrue(p['objective_policy']['actor_ranking_enabled']);self.assertEqual(p['retention']['coefficient'], 1.)
        for change in (lambda q:q['retention'].update(coefficient=0.), lambda q:q['optimizer'].update(weight_decay=.01),
            lambda q:q['parameter_partition']['active_rows'].update({'presence.bias': [2, 3]})):
            bad = copy.deepcopy(p);change(bad)
            with self.assertRaises(ValueError): n['_validate_policy'](bad)

    def test_teacher_individual_boundary_masks_absence_wrong_teacher_and_ties(self):
        n = self.n;parent, rows, text, cp = fixture(n);n['_validated'](cp)
        absent, present = cp['teacher_training']['rows'][:2]
        self.assertIsNone(absent['blocks']['conditions_end']['gold_index'])
        self.assertFalse(absent['blocks']['conditions_end']['mask'])
        self.assertFalse(present['blocks']['conditions_start']['mask'])
        self.assertTrue(present['blocks']['conditions_end']['mask'])
        self.assertFalse(present['blocks']['exceptions_presence']['mask'])
        self.assertTrue(present['blocks']['modality']['mask']);self.assertEqual(present['blocks']['modality']['teacher_argmax'], 0)
        self.assertEqual(n['_log_softmax']([1e20, 1e20]), [-math.log(2)] * 2)
        self.assertEqual(n['_log_softmax']([-1e20, -1e20]), [-math.log(2)] * 2)
        self.assertEqual(n['_kl_reference']([1e20, 1e20], [-1e20, -1e20]), 0.)

    def test_recomputed_teacher_cache_hash_cannot_authorize_tampering(self):
        n = self.n;_, _, _, cp = fixture(n)
        for mode in ('mask', 'logit', 'gold', 'teacher_text', 'training_gold', 'evaluation_id'):
            with self.subTest(mode=mode):
                bad = copy.deepcopy(cp)
                if mode in ('mask', 'logit', 'gold'):
                    block = bad['teacher_training']['rows'][1]['blocks']['conditions_end']
                    if mode == 'mask': block['mask'] = False
                    elif mode == 'gold': block['gold_index'] = 1
                    else: block['logits'][0] = 8.
                    bad['teacher_training']['rows_sha256'] = digest(bad['teacher_training']['rows'])
                    bad['teacher_training_sha256'] = digest(bad['teacher_training'])
                elif mode == 'teacher_text': bad['teacher_capture_utf8'] = bad['teacher_capture_utf8'].replace('3.0', '8.0', 1)
                elif mode == 'training_gold': bad['teacher_training_examples'][1]['fixture_labels']['modality'] = 2
                else: bad['teacher_training_examples'][1]['id'] = 'old_tune-forbidden'
                bad['initial_checkpoint_sha256'] = digest(n['_origin'](bad))
                with self.assertRaises(ValueError): n['_validated'](bad)

    def test_teacher_authenticates_complete168_source_order_and_scores(self):
        n = self.n;_, rows, text, cp = fixture(n);records = n['_training_records'](rows)
        capture = json.loads(text);row = capture['occurrences'][0]
        for mutate in (lambda x:x.update(id='eval'), lambda x:x.update(source_sha256='0' * 64),
            lambda x:x['scores']['tokens'][0].update(start=99), lambda x:x['scores']['modality_logits'].__setitem__(0, True),
            lambda x:x['scores']['start_logits']['actor'].append(1.)):
            bad = copy.deepcopy(row);mutate(bad)
            with self.assertRaises(ValueError):n['_teacher_row'](bad, records[0], 0)
        with self.assertRaises(ValueError):n['_teacher_text'](text + b' ')
        with self.assertRaises(ValueError):n['_teacher_targets'](text, rows[::-1], digest(rows))

    def test_full_copy_fresh_optimizer_shapes_aliasing_and1690_masks(self):
        n = self.n;parent, _, _, cp = fixture(n)
        self.assertEqual(cp['model_state'], parent['model_state']);self.assertIsNot(cp['model_state'], parent['model_state'])
        self.assertEqual(cp['optimizer_state']['parameters'], {});self.assertEqual(sum(len(v) * (64 if k.endswith('weight') else 1) for k, v in n['_inactive_state'](cp['model_state']).items()), 1690)
        moments = {'schema': 'adam-default-betas-eps/v1', 'parameters': {}}
        for name, shape in n['_trainable_shapes']().items():
            zero = [[0.] * shape[1] for _ in range(shape[0])] if len(shape) == 2 else [0.] * shape[0]
            moments['parameters'][name] = dict(step=1, exp_avg=copy.deepcopy(zero), exp_avg_sq=copy.deepcopy(zero))
        n['_validate_optimizer_state'](moments, 1)
        for name in ('actor_start.bias', 'start.bias', 'presence.bias'):
            bad = copy.deepcopy(moments);bad['parameters'][name]['exp_avg'][n['_inactive_rows'](name)[0]] = 1.
            with self.assertRaises(ValueError):n['_validate_optimizer_state'](bad, 1)
        for badvalue in (True, float('nan'), float('inf')):
            bad = copy.deepcopy(cp);bad['model_state']['actor_attention.query'][0] = badvalue
            with self.assertRaises(ValueError):n['_validated'](bad)
        class Parameter:
            def __init__(self, shape, address):self.shape=shape;self.address=address;self.grad='stale'
            def numel(self):return math.prod(self.shape)
            def requires_grad_(self, enabled):self.enabled=enabled
            def untyped_storage(self):return self
            def data_ptr(self):return self.address
        names={name:Parameter(n['_trainable_shapes']().get(name,(1,)),i) for i,name in enumerate(n['MODEL_PARAMETER_NAMES'])}
        model=SimpleNamespace(named_parameters=lambda:list(names.items()));_, selected=n['_configure_parameters'](model)
        self.assertEqual(selected,[names[k] for k in n['TRAINABLE_PARAMETER_NAMES']]);self.assertEqual(sum(p.enabled for p in names.values()),14)
        self.assertTrue(all(p.grad is None for p in names.values()))
        names['presence.bias'].address=names['modality.bias'].address
        with self.assertRaises(ValueError):n['_configure_parameters'](model)

    def test_trace_teacher_join_catches_recomputed_mask_and_logit_metadata(self):
        n=self.n;_,_,_,cp=fixture(n);teacher=cp['teacher_training'];row=teacher['rows'][1]
        blocks={name:{**copy.deepcopy(value), 'candidate_logits':list(value['logits']), 'kl_float32':0.} for name,value in row['blocks'].items()}
        e=dict(indices=[1],details=dict(retention=dict(rows=[dict(id=row['id'],training_index=1,source_sha256=row['source_sha256'],blocks=blocks)],
            teacher_rows_sha256=teacher['rows_sha256'],teacher_capture_sha256=n['TEACHER_CAPTURE_SHA256'])))
        n['_validate_teacher_entry'](e,teacher)
        for mode in ('mask','logit','row_index','digest'):
            bad=copy.deepcopy(e)
            if mode=='mask':bad['details']['retention']['rows'][0]['blocks']['conditions_end']['mask']=False
            elif mode=='logit':bad['details']['retention']['rows'][0]['blocks']['conditions_end']['logits'][0]=9.
            elif mode=='row_index':bad['indices']=[True]
            else:bad['details']['retention']['teacher_rows_sha256']='0'*64
            with self.assertRaises(ValueError):n['_validate_teacher_entry'](bad,teacher)

    def test_actual_retention_kernel_sixB_padding_masked_zero_and_outer_coefficient(self):
        n=self.n
        class Scalar:
            def __init__(self,v,g=None):self.v=float(v);self.g=g or {}
            def __float__(self):return self.v
            def detach(self):return Scalar(self.v)
            def __add__(self,o):
                o=o if isinstance(o,Scalar) else Scalar(o)
                return Scalar(self.v+o.v,{k:self.g.get(k,0.)+o.g.get(k,0.) for k in self.g.keys()|o.g.keys()})
            __radd__=__add__
            def __neg__(self):return Scalar(-self.v,{k:-v for k,v in self.g.items()})
            def __sub__(self,o):return self+-o
            def __mul__(self,o):
                o=o if isinstance(o,Scalar) else Scalar(o)
                return Scalar(self.v*o.v,{k:self.g.get(k,0.)*o.v+o.g.get(k,0.)*self.v for k in self.g.keys()|o.g.keys()})
            __rmul__=__mul__
            def __truediv__(self,o):return self*(1./o)
        class Vector:
            dtype='fake-f64';device='cpu'
            def __init__(self,values):self.values=values
            def __getitem__(self,i):return Vector(self.values[i]) if isinstance(i,slice) else self.values[i]
            def detach(self):return Vector([Scalar(v.v) for v in self.values])
            def tolist(self):return [v.v for v in self.values]
            def exp(self):return Vector([Scalar(math.exp(v.v),{k:math.exp(v.v)*g for k,g in v.g.items()}) for v in self.values])
            def __sub__(self,o):return Vector([a-b for a,b in zip(self.values,o.values,strict=True)])
            def __mul__(self,o):return Vector([a*b for a,b in zip(self.values,o.values,strict=True)])
            def sum(self):return sum(self.values,Scalar(0.))
        def logsoftmax(vector,dim):
            self.assertEqual(dim,0);vs=vector.values;mx=max(v.v for v in vs);z=math.fsum(math.exp(v.v-mx) for v in vs)
            probabilities=[math.exp(v.v-mx)/z for v in vs];keys=set().union(*(v.g for v in vs))
            return Vector([Scalar((v.v-mx)-math.log(z),{k:v.g.get(k,0.)-math.fsum(p*w.g.get(k,0.) for p,w in zip(probabilities,vs,strict=True)) for k in keys}) for v in vs])
        class Head:
            def __init__(self,name):self.name=name
            def __getitem__(self,key):
                if not isinstance(key,tuple):key=(key,)
                row=key[0]
                if self.name=='modality':block='modality';width=3
                elif self.name=='presence':block='exceptions_presence';width=2
                else:block=('actor_' if key[1]==0 else 'conditions_')+self.name;width=3
                vector=Vector([Scalar(0. if i<2 or width==3 and block=='modality' else 9e10,{(row,block,i):1.}) for i in range(width)])
                if self.name=='modality' and len(key)>1:return vector[key[1]]
                return vector[key[2]] if len(key)>2 else vector
        output={k:Head(k) for k in ('modality','presence','start','end')}
        torch=SimpleNamespace(tensor=lambda values,**kw:Vector([Scalar(v) for v in values]),nn=SimpleNamespace(functional=SimpleNamespace(log_softmax=logsoftmax)))
        records=[dict(id='fake-'+str(i),source_text='actor acts') for i in range(2)];rows=[]
        for i,record in enumerate(records):
            blocks={b:dict(logits=[0.]*(3 if b=='modality' else 2),gold_index=None,teacher_argmax=0,mask=False) for b in n['RETENTION_BLOCKS']}
            blocks['exceptions_presence'].update(logits=[0.,8.],gold_index=0,teacher_argmax=1,mask=False)
            rows.append(dict(id=record['id'],training_index=i,source_sha256=hashlib.sha256(record['source_text'].encode()).hexdigest(),token_count=2,blocks=blocks))
        rows.extend(copy.deepcopy(rows[0]) for _ in range(166))
        def teacher():return dict(rows=rows,rows_sha256=digest(rows))
        zero,details=n['_retention_loss'](torch,output,records,[0,1],teacher())
        self.assertEqual(zero.v,0.);self.assertTrue(zero.g);self.assertTrue(all(v==0. for v in zero.g.values()))
        rows[0]['blocks']['actor_start'].update(logits=[math.log(.75),math.log(.25)],gold_index=0,teacher_argmax=0,mask=True)
        expected=.75*math.log(1.5)+.25*math.log(.5)
        one,_=n['_retention_loss'](torch,output,records[:1],[0],teacher());half,_=n['_retention_loss'](torch,output,records,[0,1],teacher())
        self.assertAlmostEqual(one.v,expected/6);self.assertAlmostEqual(half.v,expected/12)
        self.assertAlmostEqual(one.g[(0,'actor_start',0)],-.25/6)
        self.assertNotIn((0,'actor_start',2),one.g)
        self.assertTrue(all(v==0. for k,v in half.g.items() if k[1]=='exceptions_presence'))
        rows[1]['blocks']['actor_start']=copy.deepcopy(rows[0]['blocks']['actor_start'])
        both,_=n['_retention_loss'](torch,output,records,[0,1],teacher());self.assertAlmostEqual(both.v,one.v)
        n['ranking']._loss=lambda *args:(Scalar(2.),dict(total_loss=2.))
        total,details=n['_loss'](torch,output,records,[0,1],n['_policy']('joint-readout-retention-hinge'),teacher())
        self.assertAlmostEqual(total.v,2.+one.v);self.assertEqual(details['retention']['denominator'],12)

    def test_factory_routes_full_width_selected_rows_outside_no_grad(self):
        n=self.n;state=dict(depth=0,rng=91);events=[]
        class RNG:
            def __init__(self,x):self.x=x
            def clone(self):return RNG(self.x)
        class Guard:
            def __enter__(self):state['depth']+=1
            def __exit__(self,*args):state['depth']-=1
        class Tensor:
            def __init__(self,rows=(frozenset(),),head=False):self.rows=list(rows);self.head=head
            def all(self):return False
            def __bool__(self):return False
            def __eq__(self,other):return self
            def __invert__(self):return self
            def __getitem__(self,key):
                if self.head and isinstance(key,tuple) and len(key)>1:
                    item=key[1];return Tensor(self.rows[item] if isinstance(item,slice) else [self.rows[item]],True)
                return self
            def op(self,other):return Tensor([frozenset().union(*self.rows,*(other.rows if isinstance(other,Tensor) else []))])
            __mul__=op;__add__=op;__truediv__=op
            def sum(self,*args):return Tensor([frozenset().union(*self.rows)])
            def masked_fill(self,*args):return self
            def transpose(self,*args):return Tensor(self.rows,True)
            def detach(self):return Tensor([frozenset() for _ in self.rows],self.head)
            def retain_grad(self):pass
            def reshape(self,*args):return Tensor([frozenset().union(*self.rows[i:i+2]) for i in range(0,8,2)],True)
        class Head:
            def __init__(self,name,width):self.name=name;self.width=width
            def __call__(self,value):
                events.append((self.name,self.width,state['depth']))
                deps=frozenset().union(*value.rows)
                return Tensor([frozenset() if state['depth'] else deps|{(self.name+'.weight',i),(self.name+'.bias',i)} for i in range(self.width)])
        class Base:
            training=True
            def __init__(self):
                for name,width in [('modality',3),('presence',8),('start',6),('end',6),('actor_start',6),('actor_end',6),('conditions_presence',8)]:setattr(self,name,Head(name,width))
                self.actor_attention=SimpleNamespace(query=Tensor([{('actor_attention.query',None)}]));self.actor_context=SimpleNamespace(gate=Tensor([{('actor_context.gate',None)}]))
                self._actor_forward_accounting={'calls':0};self._conditions_forward_accounting=dict.fromkeys(range(6),0)
            def _features(self,*args):
                require(state['depth']==1,'feature encoder must be frozen');events.append(('feature',args[-1]));return Tensor(),Tensor()
        original=Base();n['refinement']._model=lambda torch,config:original
        class Function:
            @classmethod
            def apply(cls,*args):return cls.forward(None,*args)
        torch=SimpleNamespace(get_rng_state=lambda:RNG(state['rng']),equal=lambda a,b:a.x==b.x,no_grad=Guard,
            autograd=SimpleNamespace(Function=Function),is_grad_enabled=lambda:state['depth']==0,
            softmax=lambda x,dim:x,where=lambda condition,a,b:a.op(b),cat=lambda xs,dim:Tensor([r for x in xs for r in x.rows],True))
        model=n['_model'](torch,{});query=model.actor_attention.query;gate=model.actor_context.gate
        out=model.forward(None,None,Tensor(),None)
        deps=lambda value:frozenset().union(*value.rows)
        actual=frozenset().union(*(deps(v) for v in out.values()));expected={(k,i) for k in n['TRAINABLE_PARAMETER_NAMES'] for i in (n['_active_rows'](k) or (None,))}
        self.assertEqual(actual,expected);self.assertEqual([x for x in events if x[0]=='feature'],[('feature',False),('feature',True),('feature',True)])
        self.assertTrue(all(item[2]==0 for item in events if len(item)==3 and item[0]!='conditions_presence'))
        self.assertIn(('conditions_presence',8,1),events);self.assertEqual(len(events),10)
        for i in (0,1,3):self.assertEqual(out['presence'].rows[i],frozenset())
        for i in (1,2,4,5):self.assertEqual(out['start'].rows[i],frozenset());self.assertEqual(out['end'].rows[i],frozenset())
        self.assertIs(query,model.actor_attention.query);self.assertIs(gate,model.actor_context.gate);self.assertEqual(state,dict(depth=0,rng=91))
        self.assertEqual(set(model._conditions_forward_accounting.values()),{1})

    def test_budget_stops_before_restore_and_guarded_fixture_is_never_called_here(self):
        n=self.n
        for args in (dict(max_steps=True),dict(max_steps=33),dict(max_seconds=float('nan')),dict(max_seconds=33)):
            with self.assertRaises(ValueError):n['train_decoder']({},[],**args)
        p=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0);seen=[]
        for _ in range(32):
            ids=n['targeted']._batch_indices(168,p,12,1729);seen.extend(ids);p=n['targeted']._advance_progress(p,12,168)
        self.assertEqual(len(seen),384);self.assertEqual(set(seen),set(range(168)));self.assertEqual(p['optimizer_steps'],32)
        with self.assertRaisesRegex(AssertionError,'torch'):n['_restore']({})
        self.assertTrue(callable(n['run_gradient_controls']))

if __name__=='__main__':unittest.main()

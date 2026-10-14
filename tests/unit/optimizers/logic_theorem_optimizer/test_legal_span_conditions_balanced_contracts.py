"""Detached stdlib controls for the opt-in balanced loss; never import production/numerical packages."""
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

SOURCE=Path(__file__).resolve().parents[4]/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'
PREVIOUS=SOURCE.with_name('legal_span_conditions_presence.py')
PARENT=SOURCE.with_name('legal_span_actor_features.py')
RETAINED_TEST=Path(__file__).with_name('test_legal_span_actor_features_contracts.py')
PREVIOUS_TEST=Path(__file__).with_name('test_legal_span_conditions_presence_contracts.py')

def f32(value):return struct.unpack('!f',struct.pack('!f',value))[0]
def require(value,message):
    if not value:raise ValueError(message)
def deny(name,*args,**kwargs):raise AssertionError('no production/numerical import: '+name)
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def digest(value):return hashlib.sha256(raw(value)).hexdigest()
def functions(path):return {n.name:n for n in ast.parse(path.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}

def helpers():
    # Only retained inert fixture definitions are reused; no actual checkpoint/model/data is loaded.
    names={'selected','namespace','fixture','moments'};owners=functions(PREVIOUS_TEST);nodes=[owners[name] for name in names]
    require(not any(isinstance(n,(ast.Import,ast.ImportFrom)) for owner in nodes for n in ast.walk(owner)),'no detached imports')
    ns=dict(globals());ns['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(PREVIOUS_TEST)+'#detached-fixtures','exec'),ns)
    return ns

def namespace():
    ns=helpers()['namespace']();original=ns['targeted']._bounded_splits
    def bounded(rows,tuning):
        records,other=original(rows,tuning)
        for index,record in enumerate(records):
            record['labels']['presence'][3]=index>=96
            record['labels']['spans'][3]=(2,2) if index>=96 else (-100,-100)
        return records,other
    ns['targeted']._bounded_splits=bounded
    return ns

class Scalar:
    def __init__(self,value):self.value=f32(value)
    def detach(self):return self
    def __float__(self):return self.value
class Vector:
    def __init__(self,values):self.values=list(map(f32,values))
    def new_tensor(self,values):return Vector(values)
    def __mul__(self,other):return Vector([f32(a*b) for a,b in zip(self.values,other.values,strict=True)])
    def mean(self):return Scalar(sum(self.values)/len(self.values))
    def sum(self):return Scalar(sum(self.values))
    def detach(self):return self
    def tolist(self):return self.values
class Logits:
    requires_grad=True
    def __init__(self,values,seen):self.values=values;self.seen=seen
    def __getitem__(self,key):self.seen['slice']=key;return self
    def detach(self):return self
    def tolist(self):return self.values

def run_loss(ns,labels,costs):
    seen={};logits=Logits([[0.,0.] for _ in labels],seen)
    def ce(values,targets,*,reduction):
        require(values is logits and reduction=='none','per-row CE must precede weighting')
        seen.update(targets=targets,reduction=reduction);return Vector(costs)
    torch=SimpleNamespace(nn=SimpleNamespace(functional=SimpleNamespace(cross_entropy=ce)),tensor=lambda values:values)
    records=[dict(id='synthetic-'+str(i),labels=dict(presence=[True,True,False,label,False,False])) for i,label in enumerate(labels)]
    loss,details=ns['_loss'](torch,dict(presence=logits),records,list(range(len(labels))),ns['_policy']('conditions-balanced-ce'))
    batch=dict(optimizer_step=1,indices=list(range(len(labels))),ids=[r['id'] for r in records],loss=float(loss))
    entry={k:batch[k] for k in ['optimizer_step','indices','ids']};entry['details']=details
    ns['_validate_objective_entry'](entry,batch,ns['_policy']('conditions-balanced-ce'))
    return loss,details,entry,batch,seen

class Contracts(unittest.TestCase):
    def setUp(self):self.ns=namespace()
    def test_training_only_counts_derive_reduced_weights_and_equal_class_mass(self):
        ns=self.ns;b=ns['_class_balance'](dict(absent=96,present=72))
        self.assertEqual(ns['SOURCE_ACTOR_FEATURES_SHA256'],'b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3')
        self.assertEqual(ns['SOURCE_ACTOR_FEATURES_MODEL_SHA256'],'c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab')
        self.assertEqual(b['weights_rational'],[[7,8],[7,6]])
        self.assertEqual(b['weights'],[7/8,7/6]);self.assertEqual(96*b['weights'][0],72*b['weights'][1]);self.assertEqual(sum([96*b['weights'][0],72*b['weights'][1]]),168)
        self.assertEqual(b['normalization'],'fixed_batch_row_count')
        for counts in [dict(absent=72,present=96),dict(absent=95,present=73),dict(absent=96.,present=72),dict(absent=96,present=True),dict(absent=96,present=72,eval=1)]:
            with self.assertRaises(ValueError):ns['_class_balance'](counts)
    def test_prepared168_typed_labels_are_counted_and_mismatches_refused(self):
        ns=self.ns;rows=[dict(id='synthetic-'+str(i),source_text='actor acts object') for i in range(168)]
        records=ns['_training_records'](rows);self.assertEqual(ns['_conditions_class_counts'](records),dict(absent=96,present=72))
        records[0]['labels']['presence'][3]=True
        with self.assertRaises(ValueError):ns['_class_balance'](ns['_conditions_class_counts'](records))
        records[0]['labels']['presence'][3]=1
        with self.assertRaises(ValueError):ns['_conditions_class_counts'](records)
        with self.assertRaises(ValueError):ns['_conditions_class_counts'](records[:-1])
        with self.assertRaises(ValueError):ns['_training_records'](rows,[dict(id='authored-reference')])
    def test_mixed_loss_is_weighted_per_row_then_mean_all_rows(self):
        ns=self.ns;labels=[False]*6+[True]*6;costs=list(range(1,13))
        loss,details,entry,batch,seen=run_loss(ns,labels,costs)
        expected=f32(sum(f32(c*f32(7/6 if label else 7/8)) for label,c in zip(labels,costs))/12)
        self.assertEqual(float(loss),expected);self.assertEqual(details['conditions_cross_entropy_unweighted'],6.5)
        self.assertNotEqual(details['conditions_cross_entropy_balanced'],6.5)
        self.assertEqual(details['total_loss'],details['conditions_cross_entropy_balanced'])
        self.assertEqual(details['batch_denominator'],12);self.assertEqual(details['batch_class_counts'],dict(absent=6,present=6))
        self.assertEqual(seen['slice'],(slice(None),1,slice(None)));self.assertEqual(seen['targets'],[0]*6+[1]*6);self.assertEqual(seen['reduction'],'none')
    def test_single_class_batches_do_not_cancel_the_weight(self):
        for label,weight in [(False,7/8),(True,7/6)]:
            loss,details,_,_,_=run_loss(self.ns,[label]*12,[2.]*12)
            self.assertEqual(float(loss),f32(2*f32(weight)))
            self.assertNotEqual(float(loss),2.)
            self.assertEqual(details['conditions_cross_entropy_unweighted'],2.)
            self.assertEqual(details['batch_denominator'],12)
    def test_trace_refuses_wrong_weights_products_denominator_counts_and_targets(self):
        ns=self.ns;_,details,entry,batch,_=run_loss(ns,[False,True],[1.,3.]);policy=ns['_policy']('conditions-balanced-ce')
        for mutate in [lambda e:e['details'].update(batch_denominator=e['details']['batch_weight_sum']),
                       lambda e:e['details'].update(conditions_cross_entropy_balanced=e['details']['conditions_cross_entropy_unweighted']),
                       lambda e:e['details']['batch_class_counts'].update(absent=0),
                       lambda e:e['details']['rows'][0].update(class_weight=f32(7/6)),
                       lambda e:e['details']['rows'][1].update(weighted_cross_entropy=3.),
                       lambda e:e['details']['rows'][0].update(conditions_present=0),
                       lambda e:e['details']['rows'][0].update(unweighted_cross_entropy=float('nan')),
                       lambda e:e['details'].update(evaluation_references_used=True),
                       lambda e:e['details'].update(actor_hinge_applied=True)]:
            bad=copy.deepcopy(entry);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_objective_entry'](bad,batch,policy)
    def test_policy_is_closed_and_new_schema_cannot_load_as_N11(self):
        ns=self.ns;policy=ns['_policy']('conditions-balanced-ce');ns['_validate_policy'](policy)
        self.assertEqual(policy['schema'],'bounded-conditions-balanced-adapter-policy/v1');self.assertTrue(policy['objective_policy']['training_row_reweighting'])
        for objective in ['conditions-presence-ce','conditions-balanced-ce-variant']:
            with self.assertRaises(ValueError):ns['_policy'](objective)
        for mutate in [lambda p:p['objective_policy']['class_balance']['weights'].reverse(),lambda p:p['objective_policy']['class_balance'].update(normalization='sum_class_weights'),lambda p:p['objective_policy'].update(training_row_reweighting=False)]:
            bad=copy.deepcopy(policy);mutate(bad)
            with self.assertRaises(ValueError):ns['_validate_policy'](bad)
        parent,rows,cp=helpers()['fixture'](ns);ns['_validated'](cp)
        self.assertEqual(cp['schema'],'bounded-conditions-balanced-adapter-checkpoint/v1')
        self.assertEqual(cp['source_actor_features_checkpoint_sha256'],ns['SOURCE_ACTOR_FEATURES_SHA256'])
        bad=copy.deepcopy(cp);bad['schema']='bounded-conditions-presence-adapter-checkpoint/v1'
        with self.assertRaises(ValueError):ns['_validated'](bad)
    def test_frozen_geometry_and_serialization_owners_are_AST_exact_N11(self):
        current,old=functions(SOURCE),functions(PREVIOUS)
        names=['_model','_configure_parameters','_partition','_initial_state','_inactive_state','_branch_digests','_state_digest','_row_invariants','_validate_freeze_entry','_frozen_head_digest','_finite_shape','_trainable_shapes','_validate_optimizer_state','_source','_origin','_validated','_restore','save_checkpoint','load_checkpoint','_write_artifact']
        for name in names:self.assertEqual(ast.dump(current[name],include_attributes=False),ast.dump(old[name],include_attributes=False),name)
        part=self.ns['_partition']();self.assertEqual((len(part['model_parameter_names']),len(part['frozen_parameter_names']),len(part['trainable_parameter_names'])),(42,40,2))
        self.assertEqual((part['stored_trainable_scalar_count'],part['active_trainable_scalar_count'],part['inactive_stored_scalar_count']),(520,130,390))
        self.assertEqual(part['active_head_rows'],[2,3]);self.assertEqual(part['inactive_head_rows'],[0,1,4,5,6,7])
    def test_scalar_balanced_CE_derivatives_have_four_thirds_ratio(self):
        weights=self.ns['_class_balance'](dict(absent=96,present=72))['weights'];h=1e-5
        def loss(a,b):return (weights[0]*math.log1p(math.exp(a))+weights[1]*math.log1p(math.exp(-b)))/2
        da=(loss(h,0)-loss(-h,0))/(2*h);db=(loss(0,h)-loss(0,-h))/(2*h)
        self.assertAlmostEqual(da,weights[0]/4,places=10);self.assertAlmostEqual(db,-weights[1]/4,places=10);self.assertAlmostEqual(abs(db/da),4/3,places=9)
    def test_budget_and_capture_bounds_precede_numerical_restore(self):
        ns=self.ns
        for args in [dict(max_steps=33),dict(max_steps=True),dict(max_seconds=float('nan')),dict(max_seconds=33)]:
            with self.assertRaises(ValueError):ns['train_decoder']({},[],**args)
        with self.assertRaisesRegex(AssertionError,'no production/numerical import: torch'):ns['_restore']({})
        for rows in [[],[{}]*129]:
            with self.assertRaises(ValueError):ns['captured_inference'](None,None,None,None,rows)

if __name__=='__main__':unittest.main()

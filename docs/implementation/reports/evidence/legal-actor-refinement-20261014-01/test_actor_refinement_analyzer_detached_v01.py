#!/usr/bin/env python3
"""Detached F15 analyzer controls: source + synthetic metadata only."""
import ast
import copy
import math
import hashlib
import json
from pathlib import Path
import runpy
import struct
import unittest

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'analyze_actor_refinement_v01.py'
NS=runpy.run_path(str(SOURCE),run_name='detached_actor_refinement_analyzer')
CONTRACT=json.loads((ROOT/'evaluation-contract-v01.json').read_bytes())
SCOPES=tuple(CONTRACT['paired_scored_scopes'])
FIELDS=NS['FIELDS']


def scores():
    return dict(tokens=[dict(text='A',start=0,end=1),dict(text='B',start=2,end=3)],modality_logits=[1.,2.,3.],
        presence_logits={r:[1.,2.] for r in FIELDS[2:]},start_logits={r:[1.,2.] for r in FIELDS},end_logits={r:[2.,1.] for r in FIELDS})


def fixture():
    records={}
    for state in NS['STATES']:
        for panel in SCOPES:
            count=168 if panel=='training168' else NS['COUNTS'][panel]
            correct=(155 if state=='trained' else 154) if panel=='training168' else min(20,count)
            records[state,panel]=[dict(id=panel+str(i),raw_exact_ir=i<correct,joint_exact_ir=i<correct) for i in range(count)]
    permissions={state:dict(count=32,ids=['p'+str(i) for i in range(32)],raw_P_to_P=32,joint_P_to_P=32,losses=0,abstentions=0) for state in NS['STATES']}
    return records,permissions


class DetachedAnalyzerControls(unittest.TestCase):
    def test_exact_immutable_helpers_only(self):
        self.assertEqual(len(NS['PURE_FUNCTIONS']),34)
        self.assertEqual(NS['pin'](NS['PURE_SOURCE'],NS['PURE_SOURCE_PIN']),NS['PURE_SOURCE_PIN'])
        self.assertNotIn('training_metadata',NS)
        self.assertEqual(NS['FREEZE_PASSED'],False)

    def test_no_reference_read_before_freeze(self):
        with self.assertRaises(ValueError):NS['read'](ROOT/'not-a-real-reference.json')

    def test_exact62_output_geometry(self):
        self.assertEqual(len(NS['expected_names']()),62)
        self.assertIn('trained-frozen-head-retention.json',NS['expected_names']())

    def test_only_actor_pointer_changes_allowed(self):
        a=scores();b=copy.deepcopy(a)
        for side in ('start_logits','end_logits'):b[side]['actor'][0]+=7.
        self.assertEqual(NS['binary'](NS['projection'](a,False)),NS['binary'](NS['projection'](b,False)))
        self.assertNotEqual(NS['binary'](NS['projection'](a)),NS['binary'](NS['projection'](b)))

    def test_every_protected_head_detects_bit_drift(self):
        a=scores()
        paths=[('modality_logits',0)]+[('presence_logits',r,0) for r in FIELDS[2:]]+[(s,r,0) for s in ('start_logits','end_logits') for r in FIELDS if r!='actor']
        for path in paths:
            with self.subTest(path=path):
                b=copy.deepcopy(a);x=b
                for key in path[:-1]:x=x[key]
                x[path[-1]]+=1.
                self.assertNotEqual(NS['binary'](NS['projection'](a,False)),NS['binary'](NS['projection'](b,False)))

    def test_signed_zero_preserved_for_conditions(self):
        a=scores();b=copy.deepcopy(a);a['presence_logits']['conditions'][0]=0.;b['presence_logits']['conditions'][0]=-0.
        self.assertNotEqual(NS['binary'](NS['projection'](a,False)),NS['binary'](NS['projection'](b,False)))

    def test_missing_conditions_or_nonactor_shape_refused(self):
        a=scores();del a['presence_logits']['conditions']
        with self.assertRaises(ValueError):NS['projection'](a,False)
        a=scores();a['start_logits']['object'].append(1.)
        with self.assertRaises(ValueError):NS['projection'](a,False)

    def test_binary32_exactness_and_nonfinite(self):
        for v in (.1,float('inf'),True):
            with self.subTest(v=v),self.assertRaises(ValueError):NS['binary'](v)

    def test_candidate_and_N11_joint_schemas_replay(self):
        rows=[dict(id='a',source_text='A')];raw=dict(occurrences=[dict(scores={'x':1})]);expected=dict(status='selected',canonical_ir={'rules':[]})
        joint={'select_joint_spans':lambda text,sc,top_k,max_search_nodes:expected}
        for schema in ('actor-refinement-joint-panel/v1','conditions-presence-joint-panel/v1'):
            value=dict(schema=schema,top_k=8,max_search_nodes=50000,rows=[dict(id='a',result=expected)])
            self.assertEqual(NS['validate_joint'](value,raw,rows,joint),value['rows'])

    def test_unknown_joint_schema_wrong_caps_ID_replay_refuse(self):
        rows=[dict(id='a',source_text='A')];raw=dict(occurrences=[dict(scores={})]);joint={'select_joint_spans':lambda *a,**kw:{'status':'selected'}}
        base=dict(schema='actor-refinement-joint-panel/v1',top_k=8,max_search_nodes=50000,rows=[dict(id='a',result={'status':'selected'})])
        for key,value in [('schema','unknown/v1'),('top_k',9),('max_search_nodes',49999),('rows',[dict(id='b',result={'status':'selected'})]),('rows',[dict(id='a',result={'status':'abstained'})])]:
            bad=copy.deepcopy(base);bad[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):NS['validate_joint'](bad,raw,rows,joint)

    def test_exact155_both_views_is_accepted(self):
        records,p=fixture();result=NS['scientific_acceptance'](CONTRACT,records,p)
        self.assertTrue(result['scientific_success']);self.assertEqual(result['training168']['raw_full_IR'],155)

    def test_either_training_view154_is_false_outcome(self):
        for route in ('raw','joint'):
            records,p=fixture();records['trained','training168'][154][route+'_exact_ir']=False
            self.assertFalse(NS['scientific_acceptance'](CONTRACT,records,p)['scientific_success'])

    def test_each_scope_and_view_loss_vetoes_net_gain(self):
        for panel in SCOPES:
            for route in ('raw','joint'):
                records,p=fixture();records['trained',panel][0][route+'_exact_ir']=False;records['trained',panel][-1][route+'_exact_ir']=True
                result=NS['scientific_acceptance'](CONTRACT,records,p)
                self.assertFalse(result['scientific_success']);self.assertEqual(result['no_complete_IR_loss_IDs_vs_N11']['loss_ids_by_scope'][panel][route],[panel+'0'])

    def test_permission_failure_is_reportable(self):
        records,p=fixture();p['trained'].update(raw_P_to_P=31,losses=1)
        result=NS['scientific_acceptance'](CONTRACT,records,p)
        self.assertTrue(result['technical_gate_passed']);self.assertFalse(result['scientific_success'])
        p['trained'].update(losses=0,abstentions=1);self.assertFalse(NS['scientific_acceptance'](CONTRACT,records,p)['scientific_success'])

    def test_joint_decoded_coupling_is_reported_without_technical_veto(self):
        rule=dict(modality='O',**{f:'A' if f in ('actor','action') else None for f in FIELDS})
        left=dict(status='decoded',canonical_ir=dict(rules=[rule]));right=copy.deepcopy(left);right['canonical_ir']['rules'][0]['modality']='P'
        before=dict(occurrences=[dict(id='a')],inference=dict(rows=[left]));after=copy.deepcopy(before)
        result=NS['decoded_coupling'](before,after,[dict(result=left)],[dict(result=right)])
        self.assertEqual(result['joint']['field_value_changes_when_both_selected']['modality'],dict(count=1,ids=['a']))

    def test_preregistered_threshold_cannot_change(self):
        contract=copy.deepcopy(CONTRACT);contract['strict_scientific_success']['training168']['minimum_accepted_raw_and_joint']=154
        with self.assertRaises(ValueError):NS['scientific_acceptance'](contract,*fixture())

    def test_no_extra_state_or_missing_scope(self):
        records,p=fixture();del records['parent','fresh_dev']
        with self.assertRaises(ValueError):NS['scientific_acceptance'](CONTRACT,records,p)

    def test_pinned_stable_CE_huge_equal_logit_regression(self):
        tree=ast.parse(NS['PURE_SOURCE'].read_bytes())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='training_metadata')
        nll=next(n for n in ast.walk(function) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='nll' for t in n.targets))
        self.assertEqual(ast.unparse(nll.value),'math.log(math.fsum((math.exp(v - maximum) for v in logits))) + (maximum - logits[target])')
        for logits,target in [([0.,0.],0),([1e30,1e30],0),([-1e30,-1e30],1),([1e30,-1e30],0)]:
            namespace=dict(math=math,logits=logits,target=target,maximum=max(logits))
            exec(compile(ast.Module(body=[nll],type_ignores=[]),'pinned-stable-CE-expression','exec'),namespace)
            self.assertAlmostEqual(namespace['nll'],math.log(2.) if logits[0]==logits[1] else 0.)
        # F15 trace lacks row logits: analyzer/recount explicitly do not claim scalar CE replay.

    def test_actual_trace_helper_pins_load_without_model_import(self):
        trace=NS['load_trace_helpers']()
        self.assertEqual(trace['TRAINING_SOURCE_PINS'][0]['sha256'],'a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e')
        self.assertEqual(len(trace['load_training_validators']()['trainer']['MODEL_PARAMETER_NAMES']),42)

    def test_actor_rank_is_diagnostic_and_float32_stable(self):
        a=scores();a['start_logits']['actor']=[0.,4.];a['end_logits']['actor']=[0.,0.]
        b=copy.deepcopy(a);b['start_logits']['actor']=[8.,0.]
        self.assertNotEqual(NS['span_ranking'](a,'actor'),NS['span_ranking'](b,'actor'))
        records,p=fixture();self.assertTrue(NS['scientific_acceptance'](CONTRACT,records,p)['scientific_success'])


if __name__=='__main__':unittest.main(verbosity=2)

"""Exercise production harness guards with synthetic metadata only.

AST extraction avoids package startup, model imports, checkpoint parsing, live
resource access and reading any saved score or evaluation reference body.
"""
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

F = Path(__file__).resolve().parent
RUNNER = F / 'run_actor_context_ranking_v04.py'
OUTPUT = F / 'actor-context-ranking-harness-author-controls-v02.json'
sys.dont_write_bytecode = True


def descriptor(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def extract():
    tree = ast.parse(RUNNER.read_bytes())
    functions = {'require', 'canonical', 'digest', 'validate_plan', 'binary',
                 'compare_captures', 'qualify_training_membership'}
    assignments = {'F', 'N6', 'LEGACY_RUNNER', 'LEGACY_SHA', 'RUN_ROOT', 'CELL', 'ATTEMPT',
                   'OLD_PANELS', 'FRESH_PANELS', 'PANELS', 'COUNTS', 'SOURCE_SHA', 'SOURCE_STATE_SHA', 'PLAN_KEYS'}
    nodes = [node for node in tree.body if
        isinstance(node, ast.FunctionDef) and node.name in functions or
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in assignments for t in node.targets)]
    scope = dict(__file__=str(RUNNER), Path=Path, hashlib=hashlib, json=json, math=math, struct=struct)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), scope)
    return SimpleNamespace(**{key: scope[key] for key in functions | assignments})


r = extract()


def plan_fixture():
    items = {}
    def pin(name, size=1, sha='a'*64):
        result = dict(path=str(F / name), bytes=size, sha256=sha)
        items[result['path']] = {k:result[k] for k in ('bytes','sha256')}
        return result
    pairs = {name:{v:pin(name+'-'+v+'.synthetic') for v in ('raw','joint')} for name in (*r.PANELS,'training168')}
    for path in (str(RUNNER), str(F / 'run_scope_guardian_v04.py'), str(r.LEGACY_RUNNER)):
        items[path] = dict(bytes=1,sha256='a'*64)
    result = dict(schema='actor-context-ranking-cell-plan/v1', package_root=str(F / 'datasets'),
        runner_path=str(RUNNER), guardian_path=str(F / 'run_scope_guardian_v04.py'),
        attempt_name=r.ATTEMPT, cell=r.CELL, source_owner_pins={str(i):pin('owner-'+str(i)) for i in range(40)},
        artifacts=items, data_export=pin('sources.synthetic'), fresh_source_export=pin('fresh.synthetic'),
        source_checkpoint=pin('donor.synthetic',12230969,r.SOURCE_SHA), source_model_state_sha256=r.SOURCE_STATE_SHA,
        context_contract={}, training_manifest_sha256='b'*64,
        legacy_prefix_sha256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
        source_reference_panels=pairs, ctypes_dl_resolution={},
        forbidden_reference_paths=[str(F.parent / 'legal-temporal-attention-20261013-01' / n) for n in
            ('fresh-reference-packet-v01.json','build_fresh_authored_temporal_reference_v02.py','fresh-reference-independent-review-v01.json')]
            + [str(F / n) for n in ('diagnose_actor_context_ranking_oracle_v01.py','actor-context-ranking-oracle-diagnostic-v01.json',
                'parent-actor-context-ranking-baseline-v01.json','postfreeze-comparator-inputs-v01.json')],
        resource_contract=dict(cpu_slots=2,rss_mib=1536,child_slots=1,storage_bytes=200000000,deadline_seconds=300),
        training_seconds=32, diagnostic_panels=[dict(name=n,count=r.COUNTS[n]) for n in r.PANELS],
        evaluation_contract=pin('contract.synthetic'), proposal=pin('design.synthetic'),
        configured_dimension=384,latent_enabled=False,default_promotion=False,Lake_executed=False,expected_loaded_owner_count=23)
    return result


def membership_fixture():
    rows = [dict(id='train-'+str(i),source_text='Synthetic source '+str(i)) for i in range(168)]
    records = [dict(row) for row in rows]
    actor = SimpleNamespace(_training_records=lambda _:records,
        targeted=SimpleNamespace(_actor_record=lambda record:(4,(0,0),{'action':(2,3)},[(1,1)])))
    batches, objectives = [], []
    for step in range(32):
        indices = [(step*12+j)%168 for j in range(12)]
        batches.append(dict(indices=indices,ids=[rows[i]['id'] for i in indices]))
        traced = [dict(id=rows[i]['id'],training_index=i,source_sha256=hashlib.sha256(rows[i]['source_text'].encode()).hexdigest(),
            token_count=4,actor_gold_coordinates=[0,0],actor_present=True,present_gold_nonactor_coordinates={'action':[2,3]},
            compatible_wrong_domain_sha256=r.digest([(1,1)]),compatible_wrong_candidate_count=1) for i in indices]
        objectives.append(dict(details=dict(rows=traced)))
    return actor,dict(batch_trace=dict(training_manifest_sha256=r.digest(rows),batches=batches),
                      objective_trace=dict(batches=objectives)),rows


def capture_fixture():
    rows = [dict(id='synthetic',source_text='Actor acts.')]
    roles = ('actor','action','object','conditions','exceptions','temporal')
    scores = dict(tokens=[dict(text='Actor',start=0,end=5)], modality_logits=[0.,1.,2.],
        presence_logits={role:[0.,1.] for role in roles[2:]},
        start_logits={role:[0.] for role in roles},end_logits={role:[0.] for role in roles})
    raw = dict(occurrences=[dict(id='synthetic',source_sha256=hashlib.sha256(b'Actor acts.').hexdigest(),scores=scores)],
               inference=dict(rows=[dict(status='decoded',canonical_ir='fixture',span_diagnostics={},minimum_decision_logit_margin=1.)]))
    joint = dict(rows=[dict(id='synthetic',result=dict(status='selected',canonical_ir='fixture'))])
    values = {'before-raw':raw,'after-raw':copy.deepcopy(raw),'before-joint':joint,'after-joint':copy.deepcopy(joint)}
    fn = r.compare_captures
    fn.__globals__['read'] = lambda path, expected:copy.deepcopy(values[path])
    pairs = [dict(raw=dict(path=state+'-raw'),joint=dict(path=state+'-joint')) for state in ('before','after')]
    return rows,values,pairs


class HarnessControls(unittest.TestCase):
    def test_closed_fixed_recipe_and_measured_owner_count(self):
        r.validate_plan(plan_fixture())
        for value in (True,0,41):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan=plan_fixture();plan['expected_loaded_owner_count']=value;r.validate_plan(plan)

    def test_wrong_donor_not_admitted_even_if_descriptor_joined(self):
        plan=plan_fixture();plan['source_checkpoint']['bytes']=9337558
        plan['artifacts'][plan['source_checkpoint']['path']]['bytes']=9337558
        with self.assertRaisesRegex(ValueError,'Exact trained F15'):
            r.validate_plan(plan)

    def test_evaluation_reference_cannot_enter_input_closure(self):
        plan=plan_fixture();plan['artifacts'][plan['forbidden_reference_paths'][0]]=dict(bytes=1,sha256='a'*64)
        with self.assertRaisesRegex(ValueError,'Reference labels'):
            r.validate_plan(plan)

    def test_manifest_membership_all_384_occurrences(self):
        actor,report,rows=membership_fixture();r.qualify_training_membership(actor,report,rows)
        self.assertEqual(sum(len(b['indices']) for b in report['batch_trace']['batches']),384)

    def test_consistent_forged_id_fails_against_training_manifest(self):
        actor,report,rows=membership_fixture()
        report['batch_trace']['batches'][0]['ids'][0]='forged'
        report['objective_trace']['batches'][0]['details']['rows'][0]['id']='forged'
        with self.assertRaisesRegex(ValueError,'exact training168'):
            r.qualify_training_membership(actor,report,rows)

    def test_source_gold_and_domain_tampering_rejected(self):
        for key,value in (('source_sha256','0'*64),('actor_gold_coordinates',[1,1]),
            ('present_gold_nonactor_coordinates',{'action':[1,3]}),('token_count',5),
            ('compatible_wrong_domain_sha256','0'*64),('compatible_wrong_candidate_count',2),
            ('training_index',True),('training_index',0.0)):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                actor,report,rows=membership_fixture()
                report['objective_trace']['batches'][0]['details']['rows'][0][key]=value
                r.qualify_training_membership(actor,report,rows)

    def test_out_of_range_actual_training_index_rejected(self):
        actor,report,rows=membership_fixture();report['batch_trace']['batches'][0]['indices'][0]=168
        with self.assertRaisesRegex(ValueError,'Bounded actual training index'):
            r.qualify_training_membership(actor,report,rows)

    def test_bitwise_signed_zero_and_finite_binary32(self):
        self.assertNotEqual(r.binary([0.]),r.binary([-0.]))
        for value in (0.1,float('nan'),float('inf'),True):
            with self.subTest(value=value),self.assertRaises(ValueError):r.binary(value)

    def test_only_actor_logits_may_change_after_training(self):
        rows,values,pairs=capture_fixture()
        values['after-raw']['occurrences'][0]['scores']['start_logits']['actor'][0]=1.
        r.compare_captures(rows,*pairs,full=False)
        with self.assertRaisesRegex(ValueError,'binary32 head parity'):
            r.compare_captures(rows,*pairs,full=True)

    def test_protected_presence_boundary_and_signed_zero_changes_rejected(self):
        for family,key in (('presence_logits','conditions'),('start_logits','action'),('end_logits','temporal')):
            with self.subTest(family=family,key=key),self.assertRaisesRegex(ValueError,'binary32 head parity'):
                rows,values,pairs=capture_fixture()
                values['after-raw']['occurrences'][0]['scores'][family][key][0]=-0.
                r.compare_captures(rows,*pairs,full=False)

    def test_complete_initial_greedy_joint_and_source_joins(self):
        for route in ('greedy','joint','source'):
            with self.subTest(route=route),self.assertRaises(ValueError):
                rows,values,pairs=capture_fixture()
                if route=='greedy':values['after-raw']['inference']['rows'][0]['canonical_ir']='changed'
                elif route=='joint':values['after-joint']['rows'][0]['result']['canonical_ir']='changed'
                else:values['after-raw']['occurrences'][0]['source_sha256']='0'*64
                r.compare_captures(rows,*pairs,full=True)


def main():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(HarnessControls)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    forbidden={'torch','numpy','transformers','sentence_transformers','huggingface_hub'}
    if any(name.split('.')[0] in forbidden for name in sys.modules):raise AssertionError('Numerical/SDK import')
    value=dict(schema='actor-context-ranking-harness-author-controls/v1',passed=result.wasSuccessful(),
        findings=[] if result.wasSuccessful() else ['Detached production guard control failed'],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),controls_source=descriptor(Path(__file__).resolve()),
        runner=descriptor(RUNNER),tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        independent_qualification=False,synthetic_only=True,actual_package_imports=0,
        checkpoint_JSON_parses=0,reference_or_saved_head_body_reads=0,private_resource_reads=0,
        model_calls=0,optimizer_updates=0,claims_acquired=0,numerical_imports=0)
    with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n')
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=value['passed'],receipt=descriptor(OUTPUT))))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()

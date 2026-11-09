"""Independent authored pure policy fixtures; no model or package-root imports.

The synthetic basis deliberately is not a numerical checkpoint and cannot pass
the enclosing original validator. These tests exercise only the pure projection
boundary, using a manually authored lexical/path table rather than its walker.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
import struct
import unittest


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value): return hashlib.sha256(wire(value)).hexdigest()


def fixture():
    # Fixed original vocabulary slots used by this closed authored fixture.
    vocab = ['"unused_'+str(i)+'"' for i in range(537)]
    mapping = {0:'<pad>',1:'<bos>',2:'<eos>',3:'"F"',4:'"O"',5:'"P"',6:'"and"',7:'"exists"',
        8:'"extension"',9:'"forall"',10:'"iff"',11:'"implies"',12:'"legal-relational-compact-content/v1"',
        13:'"not"',14:'"or"',15:'"predicate"',16:'"schema"',17:'"tree"',18:'"variable"',19:',',20:'0',21:'1',
        532:':',533:'[',534:']',535:'{',536:'}'}
    for i, token in mapping.items(): vocab[i] = token
    annotations = [
        ('{','transport',[]),('"schema"','transport',[]),(':','transport',[]),
        ('"legal-relational-compact-content/v1"','transport',[]),(',','transport',[]),('"tree"','transport',[]),(':','transport',[]),
        ('[','transport',['tree']),('"forall"','constructor',['tree',0]),(',','transport',['tree']),
        ('0','binder_declaration',['tree',1]),(',','transport',['tree']),('[','transport',['tree',2]),
        ('"forall"','constructor',['tree',2,0]),(',','transport',['tree',2]),('1','binder_declaration',['tree',2,1]),
        (',','transport',['tree',2]),('[','transport',['tree',2,2]),('"extension"','constructor',['tree',2,2,0]),
        (',','transport',['tree',2,2]),('"P"','modal_letter',['tree',2,2,1]),(',','transport',['tree',2,2]),
        ('[','transport',['tree',2,2,2]),('"predicate"','constructor',['tree',2,2,2,0]),(',','transport',['tree',2,2,2]),
        ('0','predicate_reference',['tree',2,2,2,1]),(',','transport',['tree',2,2,2]),('[','transport',['tree',2,2,2,2]),
        ('[','transport',['tree',2,2,2,2,0]),('"variable"','constructor',['tree',2,2,2,2,0,0]),
        (',','transport',['tree',2,2,2,2,0]),('0','variable_reference',['tree',2,2,2,2,0,1]),(']','transport',['tree',2,2,2,2,0]),
        (',','transport',['tree',2,2,2,2]),('[','transport',['tree',2,2,2,2,1]),('"variable"','constructor',['tree',2,2,2,2,1,0]),
        (',','transport',['tree',2,2,2,2,1]),('1','variable_reference',['tree',2,2,2,2,1,1]),(']','transport',['tree',2,2,2,2,1]),
        (']','transport',['tree',2,2,2,2]),(']','transport',['tree',2,2,2]),(']','transport',['tree',2,2]),
        (']','transport',['tree',2]),(']','transport',['tree']),('}','transport',[]),('<eos>','eos',[])]
    cp = dict(schema='legal-compact-scope-training-checkpoint/v1', objective_policy=dict(objective_kind='scope_conditional'),
              codec=dict(vocabulary=vocab), rows_utf8=[], inventories=[], scope_inventories=[])
    for row_index, modal in enumerate(('P','O')):
        annotation = deepcopy(annotations); annotation[20] = ('"'+modal+'"','modal_letter',['tree',2,2,1])
        target = ''.join(a[0] for a in annotation[:-1]); ids = [1]+[vocab.index(a[0]) for a in annotation]
        row = dict(id='independent-fixture-'+str(row_index), target_utf8=target, context_utf8='{}')
        common = dict(content_raw_sha256=hashlib.sha256(target.encode()).hexdigest(),
            context_raw_sha256=hashlib.sha256(b'{}').hexdigest(),codec_sha256=digest(cp['codec']),target_ids_sha256=digest(ids),
            authority=dict(admitted=False), training_mask=0,evaluation_gold_mask=0)
        base = dict(schema='legal-compact-content-decisions/v1',target_ids=ids,positions=[],**deepcopy(common))
        scope = dict(row_id=row['id'],positions=[],singleton_positions=39,nontrivial_positions=7,
                     supervised_positions=46,baseline_weight_sum=67.0,**deepcopy(common))
        for number,(token,role,path) in enumerate(annotation,1):
            target_id=ids[number]
            allowed = ([6,7,8,9,10,11,13,14,15] if number in (9,14,19,24)
                       else [3,4,5] if number==21 else [20,21] if number in (32,38) else [target_id])
            filtered=[i for i in allowed if not(number==9 and i==15)]
            decision='forced' if len(allowed)==1 else 'choice'
            base['positions'].append(dict(target_position=number,target_token_id=target_id,lexical_token=token,role=role,
                tree_path=path,allowed_token_ids=allowed,allowed_count=len(allowed),decision_kind=decision,prefix_ids_sha256=digest(ids[:number])))
            scope['positions'].append(dict(target_position=number,target_token_id=target_id,
                allowed_token_ids=filtered,allowed_count=len(filtered),baseline_allowed_token_ids=allowed,
                baseline_decision_kind=decision,baseline_position_weight=1.0 if decision=='forced' else 4.0,
                prefix_ids_sha256=digest(ids[:number]),removed_token_ids=sorted(set(allowed)-set(filtered))))
        cp['rows_utf8'].append(row);cp['inventories'].append(base);cp['scope_inventories'].append(scope)
    return rehash(cp)


def rehash(cp):
    for base,scope in zip(cp['inventories'],cp['scope_inventories']):
        scope['baseline_inventory_sha256']=digest(base)
    for field in ('codec','inventories','scope_inventories'): cp[field+'_sha256']=digest(cp[field])
    return cp


def run_tests(module):
    class PolicyTests(unittest.TestCase):
        def call(self,cp=None,weighting='semantic_priority',row=0,**overrides):
            cp=fixture() if cp is None else cp; policy=module.policy(weighting)
            options=dict(expected_basis_checkpoint_sha256=digest(cp),expected_policy_sha256=module.policy_sha256(policy),policy=policy)
            options.update(overrides)
            return module.prepare_inventory(cp,row,**options)
        def reject(self,change):
            cp=fixture();change(cp);rehash(cp)
            with self.assertRaises(module.RolePolicyError):self.call(cp)
        def test_01_baseline_choice_four(self):
            r=self.call(weighting='baseline');self.assertEqual(r['position_weights'],[4.0 if i in (9,14,19,21,24,32,38) else 1.0 for i in range(1,47)])
        def test_02_semantic_priority_exact_vector(self):
            r=self.call();self.assertEqual(r['position_weights'],[4.5 if i in (9,14,19,21,32,38) else 1.0 for i in range(1,47)])
        def test_03_exact_rational_and_float32_budget(self):
            for weighting in ('baseline','semantic_priority'):
                r=self.call(weighting=weighting);rationals=[Fraction(**p['weight_rational']) for p in r['positions']]
                self.assertEqual(sum(rationals),67);self.assertEqual(math.fsum(r['position_weights']),67)
                self.assertEqual(sum(rationals[i-1] for i in (9,14,19,21,24,32,38)),28)
                for w in r['position_weights']:self.assertEqual(struct.unpack('f',struct.pack('f',w))[0],w)
        def test_04_scope_sets_unchanged(self):
            cp=fixture();r=self.call(cp);self.assertEqual(r['scope_allowed_token_ids'],[p['allowed_token_ids'] for p in cp['scope_inventories'][0]['positions']])
        def test_05_same_role_rule_both_modal_rows(self):
            a,b=self.call(row=0),self.call(row=1);self.assertEqual(a['position_weights'],b['position_weights']);self.assertNotEqual(a['target_ids'][21],b['target_ids'][21])
        def test_06_outputs_detached_and_inputs_unchanged(self):
            cp=fixture();before=deepcopy(cp);a=self.call(cp);a['positions'][0]['allowed_token_ids'].append(99);a['position_weights'][0]=999
            self.assertEqual(cp,before);self.assertEqual(self.call(cp)['position_weights'][0],1)
        def test_07_roles_and_singleton_semantics(self):
            r=self.call();self.assertEqual([p['role'] for p in r['positions'] if len(p['allowed_token_ids'])>1],
                ['quantifier_constructor','quantifier_constructor','modal_constructor','modal_letter','predicate_constructor','variable_reference','variable_reference'])
            for i in (11,16,26):self.assertEqual(r['positions'][i-1]['role'],'singleton')
            self.assertFalse(r['upstream_inventory_validation_claimed']);self.assertTrue(all(v is False for v in r['authority'].values()))
        def test_08_wrong_independent_basis_hash(self):
            with self.assertRaises(module.RolePolicyError):self.call(expected_basis_checkpoint_sha256='0'*64)
        def test_09_wrong_independent_policy_hash(self):
            with self.assertRaises(module.RolePolicyError):self.call(expected_policy_sha256='0'*64)
        def test_10_plain_bounded_row_indices(self):
            for row in (True,-1,2,0.0,'0'):
                with self.subTest(row=repr(row)),self.assertRaises(module.RolePolicyError):self.call(row=row)
        def test_11_unknown_weighting(self):
            for value in ('balanced','full537',None,True):
                with self.subTest(value=repr(value)),self.assertRaises(module.RolePolicyError):module.policy(value)
        def test_12_rehashed_policy_mass_change_refused(self):
            p=module.policy('semantic_priority');p['nontrivial_role_weights']['modal_letter']['numerator']=10
            with self.assertRaises(module.RolePolicyError):self.call(policy=p,expected_policy_sha256=digest(p))
        def test_13_rehashed_wrong_role_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][13].update(role='modal_letter'))
        def test_14_rehashed_wrong_tree_path_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][37].update(tree_path=['tree',2,2,2,2,0,1]))
        def test_15_rehashed_wrong_target_id_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][13].update(target_token_id=15))
        def test_16_allowed_target_missing_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['positions'][20].update(allowed_token_ids=[3,4],allowed_count=2,removed_token_ids=[5]))
        def test_17_duplicate_allowed_token_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['positions'][31].update(allowed_token_ids=[20,20,21],allowed_count=3))
        def test_18_allowed_token_outside_baseline_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['positions'][31].update(allowed_token_ids=[20,21,22],allowed_count=3))
        def test_19_rehashed_role_population_count_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0].update(nontrivial_positions=8))
        def test_20_missing_position_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'].pop())
        def test_21_wrong_checkpoint_schema_refused(self):
            self.reject(lambda cp:cp.update(schema='other/v1'))
        def test_22_full537_objective_refused(self):
            self.reject(lambda cp:cp['objective_policy'].update(objective_kind='full537'))
        def test_23_inventory_authority_promotion_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['authority'].update(admitted=True))
        def test_24_nonordinary_and_nonfinite_inputs_refused(self):
            class Custom(dict):pass
            for cp in (Custom(fixture()),dict(bad=float('nan')),dict(bad=object())):
                with self.subTest(kind=type(cp).__name__),self.assertRaises(module.RolePolicyError):module.prepare_inventory(cp,0,expected_basis_checkpoint_sha256='0'*64,expected_policy_sha256='0'*64,policy=module.policy())
        def test_25_noncanonical_target_bytes_refused(self):
            self.reject(lambda cp:cp['rows_utf8'][0].update(target_utf8=cp['rows_utf8'][0]['target_utf8']+' '))
        def test_26_rehashed_lexical_token_annotation_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][13].update(lexical_token='"exists"'))
        def test_27_unsupported_target_geometry_refused(self):
            def change(cp):
                value=json.loads(cp['rows_utf8'][0]['target_utf8']);value['tree']=value['tree'][2]
                cp['rows_utf8'][0]['target_utf8']=wire(value).decode()
            self.reject(change)
        def test_28_rehashed_baseline_weight_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['positions'][13].update(baseline_position_weight=3.0))
        def test_29_rehashed_decision_kind_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][13].update(decision_kind='forced'))
        def test_30_newly_singleton_choice_refused(self):
            self.reject(lambda cp:cp['scope_inventories'][0]['positions'][31].update(allowed_token_ids=[20],allowed_count=1,removed_token_ids=[21]))
        def test_31_bool_tree_path_refused(self):
            self.reject(lambda cp:cp['inventories'][0]['positions'][8].update(tree_path=['tree',False]))
        def test_32_incomplete_or_extra_policy_field_refused(self):
            for change in (lambda p:p.pop('scope_policy'),lambda p:p.update(extra=True)):
                p=module.policy();change(p)
                with self.assertRaises(module.RolePolicyError):module.policy_sha256(p)
    class Result(unittest.TestResult):
        def __init__(self):super().__init__();self.successes=[]
        def addSuccess(self,test):super().addSuccess(test);self.successes.append(test._testMethodName)
    result=Result();unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests).run(result)
    return dict(schema='legal-role-policy-pure-tests/v1',passed=result.wasSuccessful(),tests_run=result.testsRun,
        successful_tests=result.successes,failures=[dict(test=t._testMethodName,traceback=trace[-2048:]) for t,trace in result.failures+result.errors],
        fixture_kind='independent synthetic committed annotations, not numerical checkpoints',model_allocations=0,training_executed=False)

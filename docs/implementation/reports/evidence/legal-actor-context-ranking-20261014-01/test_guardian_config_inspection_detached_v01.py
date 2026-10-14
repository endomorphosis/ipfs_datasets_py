"""Public-source AST and synthetic CONFIG only; no private samples or main."""
import ast
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import unittest

F = Path(__file__).resolve().parent
OBSERVER = F / 'inspect_actor_context_ranking_scheduler_config_v01.py'
CURRENT = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'
ADOPTION = F / 'adopt_shared_scheduler_actor_ranking_v02.py'
OUTPUT = F / 'guardian-config-inspection-author-controls-v01.json'


def pin(path):
    b = path.read_bytes(); return dict(path=str(path), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())


tree = ast.parse(OBSERVER.read_bytes())
functions = {'require', 'canonical', 'digest', 'source_schema', 'disclosed_value', 'config_summary'}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in functions
         or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('SET_NAMES', 'NEW_SCALARS') for t in n.targets)]
scope = dict(ast=ast, hashlib=hashlib, json=json, math=math)
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<detached-config-helpers>', 'exec'), scope)
sets, fields, profile = scope['source_schema'](CURRENT.read_bytes(), ADOPTION.read_bytes())
expected = json.loads((F/'resource-observation-policy-v01.json').read_bytes())['scheduler_config']


def summarize(value):
    return scope['config_summary'](value, expected, sets, fields, profile)


class Controls(unittest.TestCase):
    def test_historical_schema_and_exact_public_policy(self):
        v = summarize(copy.deepcopy(expected))
        self.assertTrue(v['exact_policy_config_equal']); self.assertEqual(v['unknown_key_count'], 0)

    def test_new_five_source_declared_fields_only(self):
        c = copy.deepcopy(expected)
        c.update(proof_recovery_enabled=True, proof_recovery_samples=2, proof_recovery_interval_seconds=0.25,
                 proof_recovery_grants=4, proof_resource_profile=None)
        v = summarize(c)
        self.assertEqual(set(v['additional_reviewed_keys']), scope['NEW_SCALARS'])
        self.assertFalse(v['exact_policy_config_equal'])
        self.assertTrue(all(v['known_fields'][k]['value_disclosed'] for k in scope['NEW_SCALARS']))

    def test_unknown_name_and_value_are_hidden(self):
        c = copy.deepcopy(expected); c['SYNTHETIC_PRIVATE_KEY'] = {'secret': 'SYNTHETIC_PRIVATE_VALUE'}
        v = summarize(c); raw = json.dumps(v)
        self.assertNotIn('SYNTHETIC_PRIVATE', raw); self.assertEqual(v['unknown_key_count'], 1)

    def test_opaque_container_named_lease_not_published(self):
        c = copy.deepcopy(expected); c['leases'] = {'SYNTHETIC_PRIVATE_ID': 'SYNTHETIC_PRIVATE_BODY'}
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(summarize(c)))

    def test_wrong_scalar_type_hidden(self):
        c = copy.deepcopy(expected); c['total_cpu_slots'] = 'SYNTHETIC_PRIVATE_VALUE'
        v = summarize(c)['known_fields']['total_cpu_slots']
        self.assertFalse(v['value_disclosed']); self.assertNotIn('value', v)

    def test_bool_not_integer(self):
        c = copy.deepcopy(expected); c['total_cpu_slots'] = True
        self.assertFalse(summarize(c)['known_fields']['total_cpu_slots']['value_disclosed'])

    def test_unknown_profile_hidden(self):
        c = copy.deepcopy(expected); c['proof_resource_profile'] = 'SYNTHETIC_PRIVATE_PROFILE'
        self.assertNotIn('SYNTHETIC_PRIVATE_PROFILE', json.dumps(summarize(c)))

    def test_reviewed_profile_disclosed(self):
        c = copy.deepcopy(expected); c['proof_resource_profile'] = profile
        self.assertEqual(summarize(c)['known_fields']['proof_resource_profile']['value'], profile)

    def test_changed_nested_lane_hidden(self):
        c = copy.deepcopy(expected); c['lane_reservations'] = {'SYNTHETIC_PRIVATE_LANE': {'cpu_slots': 2}}
        self.assertNotIn('SYNTHETIC_PRIVATE_LANE', json.dumps(summarize(c)))

    def test_missing_known_field_reported_without_value(self):
        c = copy.deepcopy(expected); c.pop('total_cpu_slots')
        self.assertEqual(summarize(c)['missing_expected_keys'], ['total_cpu_slots'])

    def test_integer_float_policy_difference_preserved(self):
        c = copy.deepcopy(expected); c['total_cpu_slots'] = float(c['total_cpu_slots'])
        self.assertFalse(summarize(c)['exact_policy_config_equal'])

    def test_untyped_or_unbounded_keys_refused(self):
        for c in ({1: 2}, {'x'*257: 1}, {str(i): i for i in range(257)}):
            with self.subTest(count=len(c)), self.assertRaises(ValueError): summarize(c)

    def test_negative_numeric_hidden(self):
        c = copy.deepcopy(expected); c['proof_recovery_samples'] = -1
        self.assertFalse(summarize(c)['known_fields']['proof_recovery_samples']['value_disclosed'])


if __name__ == '__main__':
    before = pin(OBSERVER)
    result = unittest.TestResult(); unittest.defaultTestLoader.loadTestsFromTestCase(Controls).run(result)
    assert result.wasSuccessful(), 'Synthetic config inspection controls failed'
    assert pin(OBSERVER) == before
    value = dict(schema='actor-context-ranking-guardian-config-inspection-author-controls/v1', passed=True, findings=[],
                 observer=before, controls_source=pin(Path(__file__).resolve()), current_scheduler_source=pin(CURRENT),
                 historical_adoption_source=pin(ADOPTION), tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                 independent_qualification=False, synthetic_CONFIG_and_public_source_AST_only=True,
                 private_sample_or_endpoint_reads=0, producer_main_calls=0, scheduler_imports=0,
                 subprocess_calls=0, API_calls=0, actual_censuses=0, model_calls=0)
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    OUTPUT.chmod(0o444); print(json.dumps(pin(OUTPUT), sort_keys=True))

"""Detached synthetic lane-disclosure controls; no private samples or main."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

F = Path(__file__).resolve().parent
OBSERVER = F / 'inspect_actor_context_ranking_scheduler_config_v02.py'
PRIOR = F / 'inspect_actor_context_ranking_scheduler_config_v01.py'
CURRENT = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'
OUTPUT = F / 'guardian-config-inspection-lane-author-controls-v02.json'


def pin(path):
    b = path.read_bytes(); return dict(path=str(path), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())


tree = ast.parse(OBSERVER.read_bytes())
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('require','disclose_reviewed_lanes')]
scope = dict(ast=ast)
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<detached-reviewed-lanes>', 'exec'), scope)
SOURCE = CURRENT.read_bytes()


def summarize(value, source=SOURCE):
    summary = dict(known_fields=dict(lane_reservations=dict(present=True, value_disclosed=False)))
    return scope['disclose_reviewed_lanes'](summary, dict(lane_reservations=value), source)


class Controls(unittest.TestCase):
    def test_reviewed_lane_values_disclosed(self):
        v = {'validation': {'cpu_slots':4,'memory_mb':0},'trainer':{'cpu_slots':2,'memory_mb':1536}}
        self.assertEqual(summarize(v)['known_fields']['lane_reservations']['value'], v)

    def test_unknown_lane_name_hidden(self):
        self.assertNotIn('SYNTHETIC_PRIVATE_LANE', json.dumps(summarize({'SYNTHETIC_PRIVATE_LANE':{'cpu_slots':1,'memory_mb':0}})))

    def test_extra_private_reservation_key_hidden(self):
        self.assertNotIn('SYNTHETIC_PRIVATE_KEY', json.dumps(summarize({'validation':{'cpu_slots':1,'memory_mb':0,'SYNTHETIC_PRIVATE_KEY':0}})))

    def test_missing_closed_key_hidden(self):
        self.assertFalse(summarize({'validation':{'cpu_slots':1}})['known_fields']['lane_reservations']['value_disclosed'])

    def test_bool_float_negative_and_large_rejected(self):
        for value in (True,1.0,-1,10**12+1):
            with self.subTest(value=value):
                self.assertFalse(summarize({'validation':{'cpu_slots':value,'memory_mb':0}})['known_fields']['lane_reservations']['value_disclosed'])

    def test_non_string_lane_hidden(self):
        self.assertFalse(summarize({1:{'cpu_slots':1,'memory_mb':0}})['known_fields']['lane_reservations']['value_disclosed'])

    def test_bounded_lane_count(self):
        self.assertFalse(summarize({str(i):{'cpu_slots':1,'memory_mb':0} for i in range(65)})['known_fields']['lane_reservations']['value_disclosed'])

    def test_non_mapping_reservation_hidden(self):
        self.assertFalse(summarize({'validation':5})['known_fields']['lane_reservations']['value_disclosed'])

    def test_empty_valid_map_disclosed(self):
        self.assertEqual(summarize({})['known_fields']['lane_reservations']['value'], {})

    def test_non_literal_enum_refused_without_execution(self):
        with self.assertRaises(ValueError):
            summarize({}, b'class ResourceLane(str, Enum):\n    X = dangerous_call()\n')

    def test_scalar_config_kernels_exactly_inherited(self):
        previous = {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(PRIOR.read_bytes()).body if isinstance(n,ast.FunctionDef)}
        current = {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name in ('require','canonical','digest','pin','public_pin','read_json','source_schema','disclosed_value','config_summary'):
            self.assertEqual(previous[name],current[name])


if __name__ == '__main__':
    before = pin(OBSERVER)
    result = unittest.TestResult(); unittest.defaultTestLoader.loadTestsFromTestCase(Controls).run(result)
    assert result.wasSuccessful(), 'Detached lane controls failed'
    assert pin(OBSERVER) == before
    receipt = dict(schema='actor-context-ranking-guardian-config-inspection-lane-author-controls/v1', passed=True, findings=[],
                   observer=before, prior_observer=pin(PRIOR), controls_source=pin(Path(__file__).resolve()),
                   current_scheduler_source=pin(CURRENT), tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   inherited_scalar_and_private_gate_kernels_exact_AST=True, prior13_author_controls_not_rerun=True,
                   independent_qualification=False, private_sample_reads=0, native_endpoint_reads=0,
                   source_producer_imports=0, producer_main_calls=0, API_calls=0, actual_censuses=0, model_calls=0)
    with OUTPUT.open('x') as stream:
        json.dump(receipt,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT),sort_keys=True))

"""Pure synthetic joint-schema compatibility controls; no saved output imports/reads."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


old = F / 'analyze_conditions_balanced_v01.py'
new = F / 'analyze_conditions_balanced_v02.py'
expected = old.read_text().replace(
    "{'conditions-balanced-joint-panel/v1','actor-features-joint-panel/v1'",
    "{'conditions-balanced-joint-panel/v1','conditions-presence-joint-panel/v1','actor-features-joint-panel/v1'")
expected = expected.replace('analyzer-source-independent-review-v01.json',
                            'analyzer-source-independent-review-v02.json')
require(expected == new.read_text(), 'Only one closed schema addition and own gate relocation permitted')
function = next(n for n in ast.parse(new.read_bytes()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'validate_joint')
namespace = dict(require=require)
exec(compile(ast.Module(body=[function], type_ignores=[]), 'detached-joint-schema', 'exec'), namespace)
calls = []


def select(text, scores, *, top_k, max_search_nodes):
    require(text == 'synthetic source' and scores == {'synthetic': True}
            and top_k == 8 and max_search_nodes == 50000, 'Exact bounded replay envelope')
    calls.append(True)
    return dict(status='selected', synthetic=True)


rows = [dict(id='synthetic-id', source_text='synthetic source')]
raw = dict(occurrences=[dict(scores={'synthetic': True})])
value = dict(schema='conditions-presence-joint-panel/v1', top_k=8, max_search_nodes=50000,
             rows=[dict(id='synthetic-id', result=dict(status='selected', synthetic=True))])
cases = []


def case(name, candidate, accepted):
    before = len(calls)
    try:
        result = namespace['validate_joint'](candidate, raw, rows, {'select_joint_spans': select})
        actual = result == candidate['rows']
    except (ValueError, KeyError):
        actual = False
    require(actual == accepted, name)
    cases.append(dict(name=name, passed=True, expected_acceptance=accepted,
                      synthetic_selector_calls=len(calls) - before))


case('actual frozen N11 producer schema accepted with exact synthetic replay', value, True)
for schema in ['conditions-balanced-joint-panel/v1', 'actor-features-joint-panel/v1',
               'actor-ranking-joint-panel/v1', 'actor-boundary-joint-panel/v1',
               'split-feature-joint-panel/v1']:
    candidate = copy.deepcopy(value); candidate['schema'] = schema
    case('prior schema retained: ' + schema, candidate, True)
for name, key, replacement in [('unknown schema refused', 'schema', 'unknown-joint-panel/v1'),
    ('wrong top_k refused', 'top_k', 7),
    ('wrong search bound refused', 'max_search_nodes', 49999)]:
    candidate = copy.deepcopy(value); candidate[key] = replacement
    case(name, candidate, False)
candidate = copy.deepcopy(value); candidate['rows'][0]['id'] = 'foreign-id'
case('source ID mismatch refused', candidate, False)
candidate = copy.deepcopy(value); candidate['rows'][0]['result']['synthetic'] = False
case('saved replay value mismatch refused', candidate, False)
candidate = copy.deepcopy(value); candidate['rows'] = []
case('incomplete row scope refused', candidate, False)
producer = F.parent / 'legal-head-repair-20261014-01/run_conditions_presence_v01.py'
producer_tree = ast.parse(producer.read_bytes())
capture = next(n for n in producer_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'capture')
require(any(isinstance(n, ast.keyword) and n.arg == 'schema'
    and isinstance(n.value, ast.Constant) and n.value.value == 'conditions-presence-joint-panel/v1'
    for n in ast.walk(capture)), 'Pinned actual N11 producer writes the exact added schema')
result = dict(schema='conditions-balanced-joint-schema-independent-controls/v1', passed=True,
    findings=[], control_count=len(cases), cases=cases, only_two_exact_source_edits=True,
    old_source=pin(old), new_source=pin(new), N11_producer_source=pin(producer),
    source=pin(Path(__file__).resolve()), actual_result_reference_savedscore_checkpoint_or_private_body_reads=0,
    full_module_or_main_calls=0, production_or_numerical_imports=0, resource_API_calls=0,
    scope='Actual AST-extracted validate_joint with synthetic rows/scores and a deterministic selector stub; no numerical selector or saved output parsed. All stable-CE/scientific functions byte unchanged.')
output = F / 'joint-schema-independent-controls-v01.json'
with output.open('x') as stream:
    json.dump(result, stream, sort_keys=True, indent=2)
    stream.write('\n');stream.flush();os.fsync(stream.fileno())
output.chmod(0o444)
print(json.dumps(pin(output), sort_keys=True))

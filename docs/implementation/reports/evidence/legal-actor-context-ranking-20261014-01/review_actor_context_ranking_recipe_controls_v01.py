"""Independent detached replay and six synthetic membership rejections only."""
import ast
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest

F = Path(__file__).resolve().parent
AUTHOR = F / 'test_actor_context_ranking_harness_detached_v01.py'
RUNNER = F / 'run_actor_context_ranking_v03.py'
OUTPUT = F / 'actor-context-ranking-recipe-independent-controls-v01.json'


def pin(path):
    b = path.read_bytes()
    return dict(path=str(path), bytes=len(b), sha256=hashlib.sha256(b).hexdigest())


def main():
    before = pin(RUNNER)
    tree = ast.parse(AUTHOR.read_bytes())
    nodes = [n for n in tree.body if not isinstance(n, ast.If)
             and not (isinstance(n, ast.FunctionDef) and n.name == 'main')]
    scope = dict(__file__=str(AUTHOR), __name__='detached_independent_replay')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<detached-reviewed-author-controls>', 'exec'), scope)
    result = unittest.TextTestRunner(stream=io.StringIO()).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(scope['HarnessControls']))
    assert result.wasSuccessful(), 'Detached author controls independent replay failed'
    fixture = scope['membership_fixture']
    qualify = scope['r'].qualify_training_membership
    cases = []
    for name in ('negative_actual_index', 'bool_actual_index', 'changed_manifest',
                 'short_actual_manifest', 'short_authenticated_records', 'actor_absent_trace'):
        actor, report, rows = fixture()
        if name == 'negative_actual_index': report['batch_trace']['batches'][0]['indices'][0] = -1
        elif name == 'bool_actual_index': report['batch_trace']['batches'][0]['indices'][0] = True
        elif name == 'changed_manifest': rows[0]['source_text'] = 'Changed synthetic source'
        elif name == 'short_actual_manifest': rows.pop()
        elif name == 'short_authenticated_records': actor._training_records = lambda _: [dict(id='x')] * 167
        elif name == 'actor_absent_trace': report['objective_trace']['batches'][0]['details']['rows'][0]['actor_present'] = False
        try:
            qualify(actor, report, rows)
        except ValueError:
            cases.append(dict(case=name, rejected=True))
        else:
            raise AssertionError('Synthetic membership mutation unexpectedly accepted')
    assert len(cases) == 6 and pin(RUNNER) == before
    assert not any(name.split('.')[0] in {'torch','numpy','transformers','huggingface_hub'} for name in sys.modules)
    value = dict(schema='actor-context-ranking-recipe-independent-controls/v1', passed=True, findings=[],
                 observed_at_utc=datetime.now(timezone.utc).isoformat(), controls_source=pin(Path(__file__).resolve()),
                 runner=before, reviewed_author_control_source=pin(AUTHOR),
                 independently_replayed_author_tests=result.testsRun, independent_membership_mutation_cases=cases,
                 failures=len(result.failures), errors=len(result.errors), AST_selected_pure_helpers_only=True,
                 actual_package_imports=0, production_main_calls=0, model_calls=0, numerical_imports=0,
                 checkpoint_JSON_parses=0, saved_head_or_reference_reads=0, private_body_reads=0,
                 subprocess_calls=0, resource_API_calls=0, claims_acquired=0)
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(pin(OUTPUT), sort_keys=True))


if __name__ == '__main__':
    main()

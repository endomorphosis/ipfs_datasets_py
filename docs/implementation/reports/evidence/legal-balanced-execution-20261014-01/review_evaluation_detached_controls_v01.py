"""Independent stdlib source checks; never opens model or reference artifacts."""
import ast
import hashlib
import json
import math
import os
from pathlib import Path

F = Path(__file__).resolve().parent
N12 = F.parent / 'legal-conditions-recall-20261014-01'


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    paths = [F / 'analyze_conditions_balanced_v01.py',
             F / 'review_conditions_balanced_result_recount_v01.py']
    trees = [ast.parse(p.read_text()) for p in paths]
    functions = [{n.name: n for n in t.body if isinstance(n, ast.FunctionDef)} for t in trees]
    prior = [N12 / 'analyze_conditions_balanced_v02.py',
             N12 / 'review_conditions_balanced_result_recount_v01.py']
    results = []

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        results.append(dict(name=name, passed=True))

    for i in range(2):
        old = {n.name: n for n in ast.parse(prior[i].read_text()).body if isinstance(n, ast.FunctionDef)}
        check('function_set_' + str(i), old.keys() == functions[i].keys())
        for name, node in old.items():
            if i == 0 and name == 'main':
                for v in ast.walk(node):
                    if isinstance(v, ast.Constant) and v.value == 'analyzer-source-independent-review-v02.json':
                        v.value = 'analyzer-source-independent-review-v01.json'
            check('unchanged_function_' + str(i) + '_' + name,
                  ast.dump(node, include_attributes=False) == ast.dump(functions[i][name], include_attributes=False))

    def expression(fn, target):
        return next(n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == target for t in n.targets))

    left = compile(ast.Expression(expression(functions[0]['training_metadata'], 'nll')), 'source-NLL', 'eval')
    right = compile(ast.Expression(expression(functions[1]['recount_training'], 'independently_computed')), 'source-softplus', 'eval')
    cases = ([1e20, 1e20], [-1e20, -1e20], [1e20, -1e20],
             [-1e20, 1e20], [1000., 999.], [-1000., -999.], [0., -0.])
    for i, values in enumerate(cases):
        for target in (0, 1):
            actual = eval(left, {'math': math, 'maximum': max(values), 'logits': values, 'target': target})
            other = eval(right, {'math': math, 'delta': values[1-target] - values[target]})
            expected = math.log(2.) if values[0] == values[1] else other
            check('stable_CE_' + str(i) + '_' + str(target),
                  math.isfinite(actual) and actual >= 0 and abs(actual-expected) <= 1e-12 * max(1., expected))

    # Validate the exact bound author controls, including every acceptance veto.
    receipt = F / 'evaluation-port-static-controls-v01.json'
    data = json.loads(receipt.read_bytes())
    check('author_control_receipt', data['passed'] is True and data['findings'] == [] and data['control_count'] == 19)
    for path, expected in data['artifacts'].items():
        check('author_artifact_' + path, pin(Path(path)) == expected)
    names = {c['name'] for c in data['controls'] if c['passed'] is True}
    check('all_scientific_vetoes_exercised', {
        'new_conditions_head_FP_ID_fails', 'new_conditions_head_FN_ID_fails',
        'new_positive_ambiguity_ID_fails', 'unrecovered_N11_FN_ID_fails',
        'raw_completeIR_loss_fails', 'joint_completeIR_loss_fails',
        'N11_required_gain_missing_fails', 'N11_target_scope_drift_refused'} <= names)
    result = dict(schema='conditions-balanced-evaluation-independent-detached-controls/v1',
                  passed=True, findings=[], control_count=len(results), controls=results,
                  artifacts={str(p): pin(p) for p in [Path(__file__).resolve(), *paths, *prior, receipt]},
                  actual_main_calls=0, actual_model_or_reference_reads=0,
                  numerical_imports=0, checkpoint_JSON_parses=0,
                  scope='Raw source AST, synthetic arithmetic and bound public controls only.')
    output = F / 'evaluation-independent-detached-controls-v01.json'
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(0o444)
    print(json.dumps(pin(output)))


if __name__ == '__main__':
    main()

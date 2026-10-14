"""Detached stdlib checks for the exact F14 evaluation metadata relocation."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import struct

F = Path(__file__).resolve().parent
N12 = F.parent / 'legal-conditions-recall-20261014-01'
OUTPUT = F / 'evaluation-port-static-controls-v01.json'


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def functions(path):
    return {node.name: node for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef)}


def main():
    require(not OUTPUT.exists(), 'Exclusive controls receipt required')
    analyzer = F / 'analyze_conditions_balanced_v01.py'
    recounter = F / 'review_conditions_balanced_result_recount_v01.py'
    original_analyzer = N12 / 'analyze_conditions_balanced_v02.py'
    original_recounter = N12 / 'review_conditions_balanced_result_recount_v01.py'
    af, rf = functions(analyzer), functions(recounter)
    ao, ro = functions(original_analyzer), functions(original_recounter)
    canonical = lambda node: ast.dump(node, include_attributes=False)
    require(af.keys() == ao.keys() and rf.keys() == ro.keys(), 'Exact original function sets required')
    require(all(canonical(af[k]) == canonical(ao[k]) for k in af if k != 'main')
            and all(canonical(rf[k]) == canonical(ro[k]) for k in rf), 'Scientific/helper function drift')
    original_main = deepcopy(ao['main'])
    class Gate(ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == 'analyzer-source-independent-review-v02.json':
                return ast.copy_location(ast.Constant('analyzer-source-independent-review-v01.json'), node)
            return node
    require(canonical(Gate().visit(original_main)) == canonical(af['main']), 'Only analyzer gate basename may change')
    for path in (analyzer, recounter):
        compile(ast.parse(path.read_text()), str(path), 'exec')
    results = []
    def check(name, action, refusal=False):
        try:
            action()
            passed = not refusal
        except ValueError:
            passed = refusal
        require(passed, 'Control failed: ' + name)
        results.append(dict(name=name, passed=True, expected_refusal=refusal))
    # These are the actual source expressions, without importing either module.
    nll = next(n.value for n in ast.walk(af['training_metadata']) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'nll' for t in n.targets))
    softplus = next(n.value for n in ast.walk(rf['recount_training']) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'independently_computed' for t in n.targets))
    for index, (logits, label) in enumerate([([1e20, 1e20], 0), ([1e20, 1e20], 1),
            ([-1e20, -1e20], 0), ([-1e20, -1e20], 1), ([100., -100.], 0),
            ([100., -100.], 1), ([-.01, .01], 0), ([-.01, .01], 1)]):
        def stable(logits=logits, label=label):
            left = eval(compile(ast.Expression(nll), 'actual-analyzer-NLL', 'eval'),
                        {'math': math, 'logits': logits, 'maximum': max(logits), 'target': label})
            delta = logits[1-label] - logits[label]
            right = eval(compile(ast.Expression(softplus), 'actual-recounter-NLL', 'eval'),
                         {'math': math, 'delta': delta})
            require(math.isfinite(left) and math.isfinite(right) and left >= 0 and right >= 0
                    and abs(left-right) <= 2e-6*max(1., abs(right)), 'Stable independent CE differs')
            if logits[0] == logits[1]:
                require(abs(left-math.log(2.)) < 1e-14, 'Equal huge logits must retain log2 CE')
        check('stable_source_CE_pair_' + str(index), stable)
    ns = dict(math=math, struct=struct, re=re, Path=Path)
    pure_names = {'require', 'f32', 'binary', 'guarded_choice', 'scientific_acceptance'}
    nodes = [af[n] for n in pure_names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(analyzer), 'exec'), ns)
    panels = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev',
              'authored_eval', 'law', 'fresh_dev', 'fresh_test')
    ns['PANELS'] = panels
    check('binary32_signed_zero_difference', lambda: require(ns['binary']([0.]) != ns['binary']([-0.]), 'Signed zero lost'))
    check('modality_exact_tie_abstains', lambda: require(ns['guarded_choice']([1., 1., 0.])[0] is None, 'Tie selected'))
    # Pure synthetic IDs exercise the complete unchanged success conjunction.
    contract = {'strict_scientific_success': {'preserve_N11_complete_IR_gain_ids':
        {'authored_dev': ['gain-dev'], 'training168': ['gain-train']},
        'recover_N11_added_FN_ids': {'expected_panel_counts': {'authored_eval': 1, 'fresh_dev': 2, 'fresh_test': 1}}}}
    summaries, records = [], {}
    for p in (*[p for p in panels if p != 'law'], 'training168'):
        ids = ['gain-dev'] if p == 'authored_dev' else ['gain-train'] if p == 'training168' else [p+'-base']
        target_ids = [p+'-FN-'+str(i) for i in range({'authored_eval': 1, 'fresh_dev': 2, 'fresh_test': 1}.get(p, 0))]
        ids += target_ids
        for state in ('parent', 'frozen_N11', 'trained'):
            buckets = {k: {'ids': []} for k in ('FP', 'FN', 'TP')}
            if state == 'frozen_N11':
                buckets['FN']['ids'] = list(target_ids)
            if state == 'trained':
                buckets['TP']['ids'] = list(target_ids)
            confusion = {'views': {'head': {'conditions': buckets}},
                'excluded_by_gold': {'head': {'conditions': {'gold_present': {'ids': []}}}}}
            summaries.append(dict(panel=p, state=state, optional_presence_confusion=confusion))
            records[state, p] = [dict(id=i, raw_exact_ir=True, joint_exact_ir=True) for i in ids]
    check('strict_all_ID_predicates_success', lambda: require(ns['scientific_acceptance'](contract, summaries, records)['scientific_success'], 'Success rejected'))
    def changed_summary(panel, state, mutate):
        data = deepcopy(summaries)
        item = next(x for x in data if x['panel'] == panel and x['state'] == state)
        mutate(item['optional_presence_confusion'])
        require(ns['scientific_acceptance'](contract, data, records)['scientific_success'] is False, 'Regression hidden')
    for metric in ('FP', 'FN'):
        check('new_conditions_head_' + metric + '_ID_fails', lambda metric=metric: changed_summary('old_tune', 'trained',
            lambda x: x['views']['head']['conditions'][metric]['ids'].append('new-error')))
    check('new_positive_ambiguity_ID_fails', lambda: changed_summary('old_tune', 'trained',
        lambda x: x['excluded_by_gold']['head']['conditions']['gold_present']['ids'].append('new-ambiguous')))
    check('unrecovered_N11_FN_ID_fails', lambda: changed_summary('fresh_dev', 'trained',
        lambda x: x['views']['head']['conditions']['TP']['ids'].pop()))
    def loss(panel, route):
        data = deepcopy(records)
        data['trained', panel][0][route+'_exact_ir'] = False
        require(ns['scientific_acceptance'](contract, summaries, data)['scientific_success'] is False, 'Complete IR loss hidden')
    check('raw_completeIR_loss_fails', lambda: loss('old_tune', 'raw'))
    check('joint_completeIR_loss_fails', lambda: loss('old_tune', 'joint'))
    check('N11_required_gain_missing_fails', lambda: loss('authored_dev', 'joint'))
    bad = deepcopy(contract)
    bad['strict_scientific_success']['recover_N11_added_FN_ids']['expected_panel_counts']['fresh_dev'] = 1
    check('N11_target_scope_drift_refused', lambda: ns['scientific_acceptance'](bad, summaries, records), True)
    artifacts = {str(p): identity(p) for p in (Path(__file__).resolve(), analyzer, recounter,
                                              original_analyzer, original_recounter)}
    result = dict(schema='conditions-balanced-evaluation-port-static-controls/v1', passed=True, findings=[],
        analyzer_function_count=len(af), recounter_function_count=len(rf),
        analyzer_all_scientific_helper_functions_AST_identical=True, analyzer_main_only_gate_basename_changed=True,
        recounter_all_function_AST_identical=True, source_contract_fixed_pin_unchanged=True,
        controls=results, control_count=len(results), actual_main_calls=0, Git_calls=0, network_calls=0,
        numerical_library_or_model_imports=0, private_body_or_endpoint_reads=0, checkpoint_JSON_parses=0,
        actual_plan_freeze_result_or_reference_reads=0, resource_API_calls=0, artifacts=artifacts,
        scope='Static relocation and detached synthetic controls only; not actual runtime/result qualification.')
    with OUTPUT.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    OUTPUT.chmod(0o444)
    print(json.dumps(identity(OUTPUT)))


if __name__ == '__main__':
    main()

"""Derive source-only F16 harness drafts from authenticated retained F15 sources.

This program writes new Python sources only. It never imports the package,
parses checkpoint bodies, observes resources or executes a model.
"""
import ast
import hashlib
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent
P = F.parent / 'legal-actor-refinement-20261014-01'
PINS = {
    'run_actor_refinement_v03.py': (37759, '3ce749fd283d7718a268afd31ff82b3df7b477f06ac98ad12fc3cf61e6384865'),
    'prepare_actor_refinement_v03.py': (13018, 'cda7fe2731cbc35e6b16f6651f80307a35bfe4df76259d84fd28b1048959c046'),
    'actor_refinement_bootstrap_smoke_controls_v03.py': (7083, 'ac05f6956034a3a2665faac5d627d640067e9c255ac5283726f883a5353d7a91'),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def retained(name):
    raw = (P / name).read_bytes()
    require((len(raw), hashlib.sha256(raw).hexdigest()) == PINS[name], 'Retained source drift: ' + name)
    return raw.decode()


def once(source, old, new):
    require(source.count(old) == 1, 'Expected unique derivation anchor: ' + old[:100])
    return source.replace(old, new)


def function(source, name, replacement):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = source.splitlines(keepends=True)
    return ''.join(lines[:node.lineno-1]) + replacement.strip() + '\n' + ''.join(lines[node.end_lineno:])


def common(source):
    return (source.replace('actor_refinement', 'actor_context_ranking')
        .replace('actor-refinement', 'actor-context-ranking')
        .replace('run_actor_context_ranking_v03.py', 'run_actor_context_ranking_v03.py')
        .replace('actor_context_ranking_resource_protocol_v03.py', 'actor_context_ranking_resource_protocol_v01.py')
        .replace('actor_context_ranking_bootstrap_smoke_controls_v03.py', 'actor_context_ranking_bootstrap_smoke_controls_v03.py')
        .replace('actor-context-ranking-bootstrap-smoke-controls-v03.json', 'actor-context-ranking-bootstrap-smoke-controls-v03.json')
        .replace("'actor-context-ranking-ce'", "'actor-context-ranking-hinge'")
        .replace('actor-context-ranking-ce-plan-v01.json', 'actor-context-ranking-hinge-plan-v01.json')
        .replace('trained N11', 'trained F15').replace('trainedN11', 'trainedF15')
        .replace('N11 saved', 'F15 saved').replace('N11 parent', 'F15 parent')
        .replace('9337558', '12230969')
        .replace('34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd',
                 'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
        .replace('b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9',
                 'a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'))


MEMBERSHIP = '''
def qualify_training_membership(actor, report, rows):
    """Join every returned ranking domain to the exact authenticated168 rows.

    Selected scalar traces cannot independently prove the full preupdate argmax.
    This verifies membership and complete gold-derived domains without forwards.
    """
    require(len(rows) == 168 and digest(rows) == report['batch_trace']['training_manifest_sha256'],
            'Exact full training manifest required for objective membership')
    records = actor._training_records(rows)
    require(len(records) == 168, 'All authenticated training records required')
    for batch, entry in zip(report['batch_trace']['batches'], report['objective_trace']['batches'], strict=True):
        for index, identifier, traced in zip(batch['indices'], batch['ids'], entry['details']['rows'], strict=True):
            require(type(index) is int and 0 <= index < 168, 'Bounded actual training index required')
            source, record = rows[index], records[index]
            count, gold, others, domain = actor.targeted._actor_record(record)
            expected = dict(id=source['id'], training_index=index,
                source_sha256=hashlib.sha256(source['source_text'].encode()).hexdigest(),
                token_count=count, actor_gold_coordinates=list(gold), actor_present=True,
                present_gold_nonactor_coordinates={role:list(v) for role,v in others.items()},
                compatible_wrong_domain_sha256=digest(domain), compatible_wrong_candidate_count=len(domain))
            require(identifier == source['id'] == record['id'] and canonical(traced) == canonical(expected),
                    'Objective trace differs from exact training168 source, labels or filtered domain')
'''


def runner():
    s = common(retained('run_actor_refinement_v03.py'))
    s = once(s, 'One bounded actor-context-ranking CE head repair from the exact trained F15 parent.',
             'One bounded actor context ranking continuation from the exact trained F15 parent.')
    s = once(s, "require(type(plan['expected_loaded_owner_count']) is int and plan['expected_loaded_owner_count']==16, 'Actual inert-bootstrap16 loaded owners required')",
             "require(type(plan['expected_loaded_owner_count']) is int and 1 <= plan['expected_loaded_owner_count'] <= 40, 'Measured inert-bootstrap owner count required')")
    s = once(s, "require(len(plan['source_owner_pins']) == 39, 'Closed retained38 plus one actor-context-ranking producer required')",
             "require(len(plan['source_owner_pins']) == 40, 'Closed retained39 plus one actor-context-ranking producer required')")
    s = once(s, "'actor-context-ranking-oracle-diagnostic-v01.json','parent-actor-context-ranking-baseline-v01.json')}",
             "'actor-context-ranking-oracle-diagnostic-v01.json','parent-actor-context-ranking-baseline-v01.json','postfreeze-comparator-inputs-v01.json')}")
    s = s.replace('source_conditions_presence_checkpoint_sha256', 'source_actor_refinement_checkpoint_sha256')
    s = s.replace('source_conditions_presence_model_state_sha256', 'source_actor_refinement_model_state_sha256')
    s = s.replace('source_conditions_presence_optimizer_steps', 'source_actor_refinement_optimizer_steps')
    s = s.replace('all42 trained N11 tensors', 'all42 trained F15 tensors')
    s = once(s, '    qualify_actor_trace(report)\n', "    qualify_actor_trace(report)\n    actor = importlib.import_module('ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_actor_context_ranking')\n    qualify_training_membership(actor, report, rows)\n")
    s = once(s, '\ndef completion(report,checkpoint,schedule,rows):', '\n' + MEMBERSHIP + '\ndef completion(report,checkpoint,schedule,rows):')
    s = once(s, "'legal_span_actor_features','legal_span_conditions_presence','legal_span_actor_context_ranking')}",
             "'legal_span_actor_features','legal_span_conditions_presence','legal_span_actor_refinement','legal_span_actor_context_ranking')}")
    anchor = '    old = read(plan[\'data_export\'][\'path\'], plan[\'data_export\'])'
    s = once(s, anchor, "    smoke_path = F / 'actor-context-ranking-bootstrap-smoke-controls-v03.json'\n    smoke = read(smoke_path, pin(smoke_path))\n    require(smoke['passed'] is True and smoke['findings'] == []\n            and smoke['loaded_owners'] == opening_owners and smoke['runner'] == pin(Path(__file__).resolve())\n            and smoke['mandatory_loaded_owners'] == sorted(required_owners)\n            and smoke['loaded_owner_count'] == plan['expected_loaded_owner_count'],\n            'Actual exact production-bootstrap receipt and measured owners required')\n" + anchor)
    return s


def preparer():
    s = common(retained('prepare_actor_refinement_v03.py'))
    s = once(s, 'Prepare exact N11 continuation inputs;', 'Prepare exact F15 continuation inputs;')
    s = once(s, "N14 = F.parent / 'legal-balanced-execution-20261014-01'", "P15 = F.parent / 'legal-actor-refinement-20261014-01'\nN14 = F.parent / 'legal-balanced-execution-20261014-01'")
    start = s.index("    previous = metadata(")
    end = s.index("    old = metadata(parent_plan_pin['path'], parent_plan_pin)", start)
    s = s[:start] + '''    contract_pin = bind(F / 'evaluation-contract-v01.json')
    contract = metadata(contract_pin['path'], contract_pin)
    parent = contract['completed_frozen_parent']
    previous = metadata(parent['completion']['path'], bind(parent['completion']['path'], parent['completion']))
    r.require(previous['schema'] == 'actor-refinement-completion/v1' and previous['phase_complete'] is True
              and previous['technical_checks_passed'] is True and previous['scientific_success'] is False
              and previous['default_promotion'] is False, 'Completed, unpublished-default F15 donor required')
    parent_plan_pin = bind(parent['plan']['path'], parent['plan'])
''' + s[end:]
    s = once(s, "    contract_pin = bind(F / 'evaluation-contract-v01.json')\n    contract = metadata(contract_pin['path'], contract_pin)\n    parent = contract['completed_frozen_parent']\n    freeze =", '    freeze =')
    s = s.replace('Exact independently qualified N11 frozen donor required', 'Exact independently qualified F15 frozen donor required')
    s = s.replace('Opaque N11 checkpoint', 'Opaque F15 checkpoint')
    s = s.replace("len(owners) == 39 and len(loaded) == 16 and len(mandatory) == 8", "len(owners) == 40 and 1 <= len(loaded) <= 40 and len(mandatory) == 9")
    s = once(s, "'legal_span_actor_features', 'legal_span_conditions_presence', 'legal_span_actor_context_ranking')}",
             "'legal_span_actor_features', 'legal_span_conditions_presence', 'legal_span_actor_refinement', 'legal_span_actor_context_ranking')}")
    s = s.replace('Exact39 declared/16 loaded/eight mandatory continuation closure required',
                  'Exact40 declared/measured loaded/nine mandatory continuation closure required')
    s = s.replace('runner-preparer-source-independent-review-v02.json', 'runner-preparer-source-independent-review-v01.json')
    s = once(s, "    forbidden += [str(N14 / n) for n in ('conditions-balanced-result-analysis-v01.json', 'conditions-balanced-independent-recount-v01.json')]",
             "    forbidden += [str(N14 / n) for n in ('conditions-balanced-result-analysis-v01.json', 'conditions-balanced-independent-recount-v01.json')]\n    forbidden += [str(P15 / n) for n in ('actor-refinement-result-analysis-v01.json', 'actor-refinement-independent-recount-v01.json')]\n    forbidden += [str(F / 'postfreeze-comparator-inputs-v01.json')]\n    # Old F15 plan references N11 saved heads; forbid their bodies in the F16 child.\n    forbidden += [item['path'] for pair in old['source_reference_panels'].values() for item in pair.values()]")
    # Roster and smoke equality come from actual source imports, never guessed counts.
    return s


def smoke():
    s = common(retained('actor_refinement_bootstrap_smoke_controls_v03.py'))
    s = once(s, "plan_path = F.parent / 'legal-head-repair-20261014-01/conditions-presence-ce-plan-v01.json'",
             "plan_path = F.parent / 'legal-actor-refinement-20261014-01/actor-refinement-ce-plan-v01.json'")
    s = s.replace("len(plan['source_owner_pins']) == 38", "len(plan['source_owner_pins']) == 39")
    s = s.replace('Exact retained38', 'Exact retained39')
    s = s.replace("len(loaded) == 16 and len(expected) == 8", "1 <= len(loaded) <= 40 and len(expected) == 9")
    s = s.replace('Exact16 loaded producers and eight actual trainers required', 'Measured loaded producers and nine actual trainers required')
    s = s.replace('All39 declared', 'All40 declared').replace('all39_raw_source_owner_pins_closed', 'all40_raw_source_owner_pins_closed')
    s = s.replace('loaded_owner_count=16, declared_owner_count=39, mandatory_loaded_owner_count=8',
                  'loaded_owner_count=len(loaded), declared_owner_count=40, mandatory_loaded_owner_count=len(expected)')
    s = s.replace('loaded_owner_count=16)))', 'loaded_owner_count=len(loaded))))')
    return s


def main():
    sources = {
        'run_actor_context_ranking_v03.py': runner(),
        'prepare_actor_context_ranking_v03.py': preparer(),
        'actor_context_ranking_bootstrap_smoke_controls_v03.py': smoke(),
    }
    for name, source in sources.items():
        ast.parse(source, filename=name)
        require(not (F / name).exists(), 'Never overwrite draft source: ' + name)
    outputs = {}
    for name, source in sources.items():
        path = F / name
        with path.open('x') as out:
            out.write(source); out.flush(); os.fsync(out.fileno())
        path.chmod(0o444)
        raw = path.read_bytes()
        outputs[name] = dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    print(json.dumps(dict(status='source_only_drafts', outputs=outputs, model_calls=0, checkpoint_JSON_parses=0)))


if __name__ == '__main__':
    main()

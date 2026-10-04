#!/usr/bin/env python3
"""Development-only structural veto evaluation on authenticated saved outputs.

No decoder, training operation or new source reference is generated. The
recognizer sees only source and committed plans. Semantic scoring is a separate
operation. Retained emitted compositions are byte-identical to the old ones;
deferred rows contain no formula or clause-prediction payload.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_checked_flat_composition_v2 as checked
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition
from scripts.ops.legal_ir import summarize_legal_timing_ownership_experiment_v2 as previous

SCHEMA = 'legal-flat-scope-saved-evaluation/v1'
POLICIES = ('original', 'distill')
MODERN = ('new', 'atom_tuning', 'atom_fresh', 'prior_condition', 'role_tuning', 'role_fresh')
GENERATION_SHA = '7bff95b22513333a2583f751ad3be214aebdddf504cd92b128dbd6ae52c577bf'
FALSE = {'training_executed': False, 'model_inference_executed': False,
    'statutory_semantics_verified': False, 'independent_scope_verified': False, 'promotion_performed': False,
    'heldout_generalization_measured': False, 'selection_or_retention_gates_revised': False}


def require(value, message):
    if not value:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def ref(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read_ref(pin):
    actual = ref(pin['path'])
    require(actual['sha256'] == pin['sha256'] and ('bytes' not in pin or actual['bytes'] == pin['bytes']),
            'authenticated file changed: ' + pin['path'])
    return json.loads(Path(pin['path']).read_bytes())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return ref(path)


def producer_pins():
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as historical_runner
    from scripts.ops.legal_ir import prepare_legal_timing_ownership_corpus as historical_corpus
    return checked.producer_pins() | gate._pins() | {
        str(Path(m.__file__).resolve()): ref(m.__file__)['sha256']
        for m in (previous, previous.retained, previous.retained.calendar, previous.retained.calendar_summary,
                  historical_runner, historical_corpus)} | {
            str(Path(__file__).resolve()): ref(__file__)['sha256']}


def verify_pins(pins):
    for path, sha in pins.items():
        require(ref(path)['sha256'] == sha, 'frozen producer changed: ' + path)


def source_rows(targets):
    return [{key: row[key] for key in ('candidate_id', 'source_text', 'source_sha256')} for row in targets]


def joined_rows(generation, sources, targets=None):
    rows = generation['rows']; by_source = {s['candidate_id']: s for s in sources}
    require(len(rows) == len(sources) == len(by_source) and
            len({r['candidate_id'] for r in rows}) == len(rows) and
            {r['candidate_id'] for r in rows} == set(by_source), 'complete unique source/prediction inventory required')
    by_target = None if targets is None else {t['candidate_id']: t for t in targets}
    if by_target is not None:
        require(len(targets) == len(by_target) == len(sources) and set(by_target) == set(by_source),
                'complete unique source/reference inventory required')
    for row in rows:
        source = by_source[row['candidate_id']]
        composition._source(source)
        require(row['source_sha256'] == source['source_sha256'], 'saved source commitment changed')
        require(row['status'] in ('composed', 'abstained') and
                (row['status'] == 'composed') == (row['composition'] is not None), 'status/composition disagree')
        if by_target is not None:
            target = by_target[row['candidate_id']]
            require(source_rows([target])[0] == source and type(target['supported']) is bool,
                    'reference source text/hash or support flag differs')
        else:
            target = None
        yield row, source, target


def filter_saved(generation, sources, cache, plan_evidence):
    """Cache only exact complete composition requests; never reference labels."""
    result = []; calls = aliases = 0
    for row, source, _ in joined_rows(generation, sources):
        value = row['composition']; evidence_key = None; report_key = None; reasons = []
        if value is not None:
            require(value['source_plan']['source'] == source, 'saved composition source differs')
            expected = value['source_plan_sha256']
            # Validate the entire old composition even for a later structural veto.
            regenerated = composition.compose_rule_list(value['source_plan'], value['clause_predictions'],
                                                       expected_plan_sha256=expected)
            require(regenerated == value, 'saved canonical/rule/occurrence ledger changed')
            report_key = digest({'source': source, 'plan': value['source_plan'],
                                 'predictions': value['clause_predictions']})
            if report_key not in cache:
                report = checked.compose_checked_flat(source, value['source_plan'], value['clause_predictions'],
                                                       expected_plan_sha256=expected)
                cache[report_key] = report; calls += 1
            else:
                report = cache[report_key]; aliases += 1
            require(report['clause_predictions_sha256'] == composition.digest(value['clause_predictions']) and
                    report['source_sha256'] == source['source_sha256'] and report['source_plan_sha256'] == expected,
                    'cached checked request differs')
            evidence_key = digest({'source': source, 'plan': value['source_plan']})
            evidence = report['dependency_evidence']
            reasons = evidence['reasons']
            if evidence_key in plan_evidence:
                require(plan_evidence[evidence_key] == evidence, 'same source/plan produced different structural evidence')
            else:
                plan_evidence[evidence_key] = evidence
            if report['status'] == 'composed':
                require(report['composition'] == value and report['canonical_ir'] == value['canonical_ir'],
                        'veto changed an accepted formula or occurrence ledger')
            else:
                require(report['status'] == 'deferred' and report['composition'] is None and report['canonical_ir'] is None,
                        'veto leaked composed formula')
                value = None
        deferred = row['composition'] is not None and value is None
        # Raw predictions remain solely in the authenticated original reference.
        result.append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
            'status': 'composed' if value is not None else 'abstained',
            'reason': 'source_dependency_outside_declared_flat_profile' if deferred else row['reason'],
            'composition': value, 'clause_generation': None,
            'segmentation_status': row['segmentation_status'],
            'structural_veto_applied': deferred, 'dependency_evidence_key': evidence_key,
            'dependency_reasons': reasons, 'checked_report_key': report_key, **FALSE})
    return {'rows': result, 'saved_predictions_only': True, **FALSE}, {'wrapper_calls': calls, 'wrapper_cache_aliases': aliases}


def score(generation, sources, targets):
    counts = Counter(); rows = []
    for row, source, target in joined_rows(generation, sources, targets):
        supported = target['supported']; value = row['composition']; accepted = value is not None
        wanted = [c['rule'] for c in target['clauses']] if supported else None
        canonical = bool(supported and accepted and value['source_rule_list'] == wanted)
        actual_intervals = [(c['char_start'], c['char_end']) for c in value['source_plan']['clauses']] if accepted else []
        wanted_intervals = [(c['char_start'], c['char_end']) for c in target['clauses']] if supported else []
        occurrence = bool(supported and accepted and actual_intervals == wanted_intervals)
        exact = canonical and occurrence
        item = {'id': row['candidate_id'], 'supported': supported, 'composed': accepted, 'exact': exact,
                'canonical_rule_list_exact': canonical, 'occurrence_boundaries_exact': occurrence,
                'decision_exact': exact or (not supported and not accepted),
                'structural_veto_applied': row.get('structural_veto_applied', False),
                'dependency_reasons': row.get('dependency_reasons', [])}
        rows.append(item)
        for key, flag in {'count': True, 'supported': supported, 'unsupported': not supported,
            'composed': accepted, 'abstained': not accepted, 'exact': exact,
            'canonical_rule_list_exact': canonical, 'occurrence_boundaries_exact': occurrence,
            'decision_exact': item['decision_exact'], 'unsupported_accepted': not supported and accepted}.items():
            counts[key] += int(flag)
    return {'metrics': dict(counts), 'rows': rows}


def check_historical_score(actual, expected):
    """Compare every common recorded count and all recorded per-source flags."""
    metric = actual['metrics']
    require({'count', 'supported', 'unsupported'} <= set(expected) and
            ('exact' in expected or 'joint_exact' in expected), 'complete historical before-score required')
    if 'joint_exact' in expected:
        require(expected['joint_exact'] == metric['exact'], 'historical joint count differs')
    for key, value in metric.items():
        if key in expected:
            require(expected[key] == value, 'historical count differs: ' + key)
    ids = {'supported_ids': [r['id'] for r in actual['rows'] if r['supported']],
           'unsupported_ids': [r['id'] for r in actual['rows'] if not r['supported']],
           'joint_exact_ids': [r['id'] for r in actual['rows'] if r['exact']],
           'unsupported_accepted_ids': [r['id'] for r in actual['rows'] if not r['supported'] and r['composed']]}
    for key, values in ids.items():
        if key in expected: require(expected[key] == sorted(values), 'historical membership differs: ' + key)
    if 'rows' in expected:
        old = {r['id']: r for r in expected['rows']}
        require(len(old) == len(actual['rows']), 'historical per-source count differs')
        for row in actual['rows']:
            for key in ('supported', 'composed', 'exact', 'canonical_rule_list_exact', 'occurrence_boundaries_exact', 'decision_exact'):
                if key in old[row['id']]: require(old[row['id']][key] == row[key], 'historical source score differs: ' + key)


def compare(before, after):
    left = {r['id']: r for r in before['rows']}; right = {r['id']: r for r in after['rows']}
    require(set(left) == set(right) and before['metrics']['count'] == after['metrics']['count'] and
            before['metrics']['supported'] == after['metrics']['supported'], 'veto changed scoring denominator')
    accepted = lambda rows: {k for k, v in rows.items() if v['composed']}
    exact = lambda rows: {k for k, v in rows.items() if v['exact']}
    require(accepted(right) <= accepted(left) and exact(right) <= exact(left), 'veto created acceptance or exactness')
    unsupported = lambda rows: sorted(k for k, v in rows.items() if not v['supported'] and v['composed'])
    return {'before': before['metrics'], 'after': after['metrics'],
        'supported_exact_lost_ids': sorted(exact(left)-exact(right)), 'supported_exact_gained_ids': [],
        'supported_acceptance_lost_ids': sorted(k for k in accepted(left)-accepted(right) if left[k]['supported']),
        'unsupported_accepted_before_ids': unsupported(left), 'unsupported_accepted_after_ids': unsupported(right),
        'unsupported_acceptance_removed_ids': sorted(set(unsupported(left))-set(unsupported(right))),
        'new_acceptance_ids': [], 'all_reject_after': not accepted(right),
        'supported_coverage_after': sum(r['supported'] and r['composed'] for r in right.values()),
        'veto_reasons': dict(Counter(reason for row in right.values() if row['structural_veto_applied']
                                    for reason in row['dependency_reasons'])),
        'per_source': [{'id': k, 'supported': left[k]['supported'], 'before': left[k], 'after': right[k]}
                       for k in sorted(left)]}


def job_identity(job):
    return digest({key: job[key] for key in ('payload_sha256', 'source_sha256', 'target_sha256')})


def create_inventory(summary_path, output):
    from scripts.ops.legal_ir import run_legal_timing_ownership_experiment as runner
    output = Path(output); require(not output.exists(), 'fresh inventory directory required'); output.mkdir(parents=True)
    summary_pin = ref(summary_path); summary = read_ref(summary_pin); gpin = summary['generation_freeze']
    require(gpin['sha256'] == GENERATION_SHA, 'exact completed timing run02 required')
    frozen = read_ref(gpin); inputs = runner.load_config(frozen['config']['path'])
    require(ref(frozen['config']['path'])['sha256'] == frozen['config']['sha256'], 'configuration binding differs')
    require(summary['fresh_reference_files_opened_after_replay_and_build_freezes'] is True and
            frozen['all_training_selection_and_generation_complete'] is True, 'historical qualification not complete')
    selection = read_ref(frozen['selections']); parents = read_ref(frozen['parent_tuning'])
    panels = {}; jobs = []
    for panel in MODERN:
        panels['modern/'+panel] = inputs['modern_document_targets'][panel]
    legacy_panels = tuple(runner.legacy.DOCUMENT_TUNING_PANELS)
    require(len(legacy_panels) == 6, 'all six historical document gates required')
    for panel in legacy_panels: panels['legacy/'+panel] = inputs['legacy'][panel]
    manifest = inputs['manifest']
    panels['development/fresh'] = read_ref(manifest['artifacts']['fresh_document_targets'])
    panels['development/role_fresh'] = inputs['modern_document_targets']['role_fresh']
    references = {}
    for panel, targets in panels.items():
        references[panel] = {'sources': write(output/'panels'/f'{panel.replace("/", "--")}-sources.json', source_rows(targets)),
                             'targets': write(output/'panels'/f'{panel.replace("/", "--")}-targets.json', targets), 'count': len(targets)}
    def add(name, model, policy, panel, pin, nested, historical_score, phase):
        payload = read_ref(pin); generation = payload['generation'] if nested else payload
        joined_rows_list = list(joined_rows(generation, source_rows(panels[panel]), panels[panel]))
        jobs.append({'name': name, 'model': model, 'policy': policy, 'panel': panel, 'phase': phase,
            'generation': pin, 'nested_generation': nested, 'payload_sha256': digest(generation),
            'source_sha256': digest(source_rows(panels[panel])), 'target_sha256': digest(panels[panel]),
            'count': len(joined_rows_list), 'recorded_metric': historical_score})
    fields_list = [('parent_'+arch+'-1730', value, 'parent') for arch, value in parents.items()]
    for trial in selection['trials']:
        for stage in trial['stages']:
            fields_list.append((trial['name']+'_stage'+str(stage['steps']), stage, 'stage'))
    require(len(fields_list) == 10, 'two parents and eight stages required')
    for model, fields, phase in fields_list:
        for panel in MODERN:
            for policy in POLICIES:
                pin = fields['fixed_documents_'+panel+'_'+policy]
                add(model+'/'+panel+'/'+policy, model, policy, 'modern/'+panel, pin, True,
                    fields['fixed_document_metrics'][panel][policy], phase)
        for panel in legacy_panels:
            for policy in ('parent', 'expanded'):
                pin = fields[panel+'_'+policy]
                add(model+'/'+panel+'/'+policy, model, 'legacy_'+policy, 'legacy/'+panel, pin, True,
                    read_ref(pin)['metrics'], phase)
    details = read_ref(summary['details'])
    models = [m for m in frozen['models'] if m['selection'] in ('unchanged_parent', 'unselected_final200_diagnostic')]
    require(len(models) == 6, 'six parent/final development models required')
    for model in models:
        for policy in POLICIES:
            pipeline = model['name']+'__boundary_'+policy
            for panel in ('fresh', 'role_fresh'):
                recorded = details['document'][pipeline][panel]
                add(pipeline+'/'+panel, model['name'], policy, 'development/'+panel,
                    frozen['document_files'][pipeline][panel], False,
                    {**recorded['metrics'], 'rows': recorded['rows']}, 'development')
    require(len(jobs) == 264, 'closed 240 admitted plus 24 development job inventory required')
    value = {'schema': SCHEMA, 'historical_qualification': summary_pin, 'historical_generation': gpin,
        'historical_selection': frozen['selections'], 'historical_details': summary['details'],
        'panels': references, 'jobs': jobs, 'logical_jobs': len(jobs), 'logical_rows': sum(j['count'] for j in jobs),
        'original_selection_decisions': [{'name': t['name'], 'selection': t['selection'],
            'stages': [{'steps': s['steps'], 'eligible': s['eligible'], 'failures': s['failures']} for s in t['stages']]}
            for t in selection['trials']], 'development_models': models,
        'native_sampling': 'first two accepted and lowerable candidate IDs per development/fresh model and policy; no reference scoring used',
        'native_candidate_limit': 24, 'all_panels_are_now_exposed_development': True, **FALSE}
    return write(output/'inventory.json', value)


def sampled_native(records, sources, *, toolchain, limit=2):
    require(type(limit) is int and 1 <= limit <= 2, 'bounded two-source sample required')
    lookup = {s['candidate_id']: s for s in sources}; entries = []; exclusions = []
    for row in sorted(records, key=lambda r: r['candidate_id']):
        if row['composition'] is None: continue
        if len(entries) == limit: break
        selected = previous.document_selection([row], [lookup[row['candidate_id']]], toolchain=toolchain)
        entries.extend(selected['rows']); exclusions.extend(selected['excluded'])
    return {'rows': entries, 'lowering_exclusions_before_sample_filled': exclusions,
            'source_count': len(sources), 'accepted_count': sum(r['composition'] is not None for r in records),
            'sample_limit': limit, 'reference_metrics_used_for_selection': False}


def native_batches(entries):
    """Deterministic batches never reuse a candidate ID within one Lake project."""
    batches = []
    for entry in entries:
        identity = entry['candidate']['candidate_id']
        batch = next((b for b in batches if len(b) < 24 and identity not in
                      {e['candidate']['candidate_id'] for e in b}), None)
        if batch is None: batches.append([entry])
        else: batch.append(entry)
    return batches


def run(inventory_pin, freeze_pin, output, *, toolchain, lake_executable):
    output = Path(output); require(not output.exists(), 'fresh evaluation attempt required')
    frozen = read_ref(freeze_pin); require(frozen['inventory'] == inventory_pin, 'frozen inventory differs')
    verify_pins(frozen['producer_pins']); require(producer_pins() == frozen['producer_pins'], 'producer inventory differs')
    for pin in frozen['tests']: read_ref(pin) if pin['path'].endswith('.json') else require(ref(pin['path']) == pin, 'test pin changed')
    require(ref(lake_executable) == frozen['lake_executable'] and toolchain == frozen['toolchain'], 'native toolchain differs')
    inventory = read_ref(inventory_pin)
    for key in ('historical_qualification', 'historical_generation', 'historical_selection', 'historical_details'):
        read_ref(inventory[key])
    output.mkdir(parents=True)
    panels = {k: {kind: read_ref(v[kind]) for kind in ('sources', 'targets')} for k, v in inventory['panels'].items()}
    cache = {}; plan_evidence = {}; physical = {}; aliases = []; metrics = {}; selected = {}; calls = 0; raw_composed = 0
    for index, job in enumerate(inventory['jobs']):
        payload = read_ref(job['generation']); generation = payload['generation'] if job['nested_generation'] else payload
        data = panels[job['panel']]; sources = data['sources']; targets = data['targets']
        require(digest(generation) == job['payload_sha256'] and digest(sources) == job['source_sha256'] and
                digest(targets) == job['target_sha256'], 'frozen generation/source/reference identity differs')
        key = job_identity(job)
        if key not in physical:
            filtered, accounting = filter_saved(generation, sources, cache, plan_evidence)
            before = score(generation, sources, targets); after = score(filtered, sources, targets)
            check_historical_score(before, job['recorded_metric'])
            change = compare(before, after); calls += accounting['wrapper_calls']; raw_composed += before['metrics']['composed']
            filtered_pin = write(output/'filtered'/f'{key}.json', {**filtered, 'original_saved_prediction': job['generation']})
            change_pin = write(output/'scores'/f'{key}.json', change)
            physical[key] = {'executed_job': job['name'], 'filtered': filtered_pin, 'score': change_pin,
                'count': len(sources), 'accounting': accounting, 'before_score': before,
                'metric': {k: v for k, v in change.items() if k != 'per_source'}}
        item = physical[key]; check_historical_score(item['before_score'], job['recorded_metric'])
        aliases.append({'logical_job': job['name'], 'executed_job': item['executed_job'], 'identity_sha256': key,
                        'filtered': item['filtered'], 'score': item['score']})
        metrics[job['name']] = item['metric']
        if job['panel'] == 'development/fresh':
            selected[job['name']] = sampled_native(read_ref(item['filtered'])['rows'], sources, toolchain=toolchain)
        if index % 12 == 0: print({'phase': 'saved_output_filter', 'logical_done': index+1, 'physical_jobs': len(physical),
                                  'wrapper_calls': calls, 'source_plan_keys': len(plan_evidence)}, flush=True)
    evidence_pin = write(output/'dependency-evidence.json', plan_evidence)
    # Full checked reports are held once; deferred reports have no formula payload.
    reports_pin = write(output/'checked-composition-reports.json', cache)
    filtered_freeze = write(output/'filtered-generation-frozen.json', {'inventory': inventory_pin,
        'implementation_freeze': freeze_pin, 'aliases': aliases, 'dependency_evidence': evidence_pin,
        'checked_reports': reports_pin, 'logical_jobs': len(aliases), 'physical_jobs': len(physical),
        'logical_rows': inventory['logical_rows'], 'physical_rows': sum(v['count'] for v in physical.values()),
        'actual_wrapper_calls': calls, 'unique_source_plan_keys': len(plan_evidence),
        'dependency_v2_prepare_calls_including_wrapper_validation': 2*calls,
        'embedded_dependency_v1_prepare_calls': 2*calls,
        'physical_pre_filter_compositions': raw_composed,
        'wrapper_request_cache_aliases': raw_composed-calls, **FALSE})
    unique = {}; native_aliases = []
    for slot, value in selected.items():
        for entry in value['rows']:
            key = digest(entry); unique.setdefault(key, entry)
            native_aliases.append({'slot': slot, 'candidate_id': entry['candidate']['candidate_id'], 'entry_sha256': key})
    require(len(selected) == 12 and len(native_aliases) <= 24, 'bounded twelve logical native samples required')
    build_selection = write(output/'native-selection-frozen.json', {'filtered_generation': filtered_freeze,
        'slots': selected, 'unique_entries': unique, 'aliases': native_aliases, 'source_only_sampling': True,
        'sampled_coverage_only': True, 'semantic_references_used_for_sample': False, **FALSE})
    print({'phase': 'filtered_generation_and_native_selection_frozen', 'unique_candidates': len(unique)}, flush=True)
    batches = []; build_index = {}
    for number, entries in enumerate(native_batches(list(unique.values()))):
        result = previous.retained.build_batches(entries, output/'native-builds'/f'group-{number:02d}',
            argparse.Namespace(toolchain=toolchain, lake_executable=lake_executable))
        for batch in result:
            batches.append(batch)
            for entry in entries:
                if entry['candidate']['candidate_id'] in batch['candidate_ids']:
                    build_index[digest(entry)] = batch
        print({'phase': 'native_batch', 'index': number, 'candidates': len(entries),
               'passed': all(b['build_passed'] for b in result)}, flush=True)
    build_freeze = write(output/'native-builds-frozen.json', {'selection': build_selection, 'batches': batches,
        'actual_backend_calls': sum(b['backend_executed'] for b in batches),
        'successful_backend_calls': sum(b['backend_executed'] and b['build_passed'] for b in batches), **FALSE})
    build_metrics = {}
    for slot, value in selected.items():
        job = next(j for j in inventory['jobs'] if j['name'] == slot); item = physical[job_identity(job)]
        change = read_ref(item['score']); exact = {r['id'] for r in change['per_source'] if r['after']['exact']}
        built = [e for e in value['rows'] if build_index[digest(e)]['build_passed']]
        build_metrics[slot] = {'source_count': value['source_count'], 'accepted_count': value['accepted_count'],
            'sampled_candidates': len(value['rows']), 'built': len(built),
            'built_joint_reference_exact': sum(e['candidate']['candidate_id'] in exact for e in built),
            'built_reference_mismatch': sum(e['candidate']['candidate_id'] not in exact for e in built)}
    verify_pins(frozen['producer_pins'])
    summary = {'schema': SCHEMA, 'inventory': inventory_pin, 'implementation_freeze': freeze_pin,
        'filtered_generation': filtered_freeze, 'native_selection': build_selection, 'native_builds': build_freeze,
        'logical_jobs': len(aliases), 'physical_jobs': len(physical), 'logical_rows': inventory['logical_rows'],
        'physical_rows': sum(v['count'] for v in physical.values()), 'logical_rows_aliased': inventory['logical_rows']-sum(v['count'] for v in physical.values()),
        'actual_wrapper_calls': calls, 'unique_source_plan_keys': len(plan_evidence),
        'physical_pre_filter_compositions': raw_composed, 'wrapper_request_cache_aliases': raw_composed-calls,
        'dependency_v2_prepare_calls_including_wrapper_validation': 2*calls,
        'embedded_dependency_v1_prepare_calls': 2*calls,
        'actual_native_calls': sum(b['backend_executed'] for b in batches), 'native_passed_calls': sum(b['build_passed'] for b in batches),
        'unique_native_candidates': len(unique), 'logical_sampled_native_candidates': len(native_aliases),
        'metrics': metrics, 'sampled_build_metrics': build_metrics,
        'original_selection_decisions': inventory['original_selection_decisions'],
        'all_panels_exposed_development': True, 'previous_native_success_reused': False,
        'scope': 'Structural veto on historical saved compositions; source-semantic gold, learned scope improvement and deployment qualification are not established.', **FALSE}
    result = write(output/'summary.json', summary); print({'phase': 'complete', 'summary': result}, flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-inventory', action='store_true'); parser.add_argument('--historical-summary')
    parser.add_argument('--inventory'); parser.add_argument('--freeze'); parser.add_argument('--output', required=True)
    parser.add_argument('--lake-executable'); parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    args = parser.parse_args(argv)
    if args.prepare_inventory:
        print(create_inventory(args.historical_summary, args.output))
    else:
        run(ref(args.inventory), ref(args.freeze), args.output, toolchain=args.toolchain, lake_executable=args.lake_executable)


if __name__ == '__main__': main()

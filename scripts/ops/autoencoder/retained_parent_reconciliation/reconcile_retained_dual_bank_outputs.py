#!/usr/bin/env python3
"""Read-only original-parent replay and retained dual-bank evidence reconciliation.

Restore only the original0b3c parent. Reuse every saved candidate/control model
output unchanged. New parent predictions precede explicit posthoc reference joins.
No fit, encoder, candidate restoration, Manager, Hub or default replacement occurs.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

COHORTS = ('original_train48', 'normative_train48', 'new_balanced_train48', 'exposed_v3_48')
TRAIN_COHORTS = COHORTS[:3]
ROLES = ('selected', 'last-attempt')
PARALLEL_ARM = 'dual-bank-retention-ce'
CONTROL_ARM = 'control-wording-ce'
PARENT_TENSOR = '0b3c7c3b1a5581cd393d9bb8db1d24b87fe2cb9dff0be268aa2b5ed1f88b6594'
FALSE = dict(qualified=False, admitted=False, proof_authority=False, checkpoint_promoted=False,
    source_semantics_verified=False, formalized=False, lake_executed=False, training_executed=False,
    encoder_executed=False, fresh_holdout=False, independent_semantic_holdout=False, used_for_selection=False)
PROFILE = dict(schema='retained-dual-bank-parent-reconciliation-plan/v1', phase='evaluation',
    dimension=384, parent_tensor_sha256=PARENT_TENSOR, cohorts=list(COHORTS), roles=list(ROLES),
    restored_models=1, new_generation_panels=4, reused_dual_panels=8, reused_archived_control_panels=8,
    paragraphs_per_panel=48, rules_per_panel=180, scalar_sites_per_panel=720,
    reused_bank_readouts=10, count_source_fields=4, source_vocabulary_size=32,
    max_target_tokens=512, batch_size=8, generation_temperature=0, cpu_slots=1, memory_mb=1536,
    storage_bytes=100000000, output_payload_cap_bytes=97000000, max_seconds_total=800,
    max_seconds_per_panel=60, max_trace_memory_bytes=268435456,
    candidate_models_restored=False, fresh_matched_control=False, auxiliary_chronology_changed=True,
    bank_mixing_effect_causally_isolated=False, v3_used_for_selection=False, sealed_scores_read=False, **FALSE)
FIELDS = {'schema', 'inputs', 'extensions', 'plan_sha256', 'numeric_source', 'evaluation_helper_source',
    'initialization_manifest', 'initialization_plan', 'initialization_extension_root', 'parallel_training_summary', 'parallel_evaluation_summary',
    'archived_control_training_summary', 'archived_control_evaluation_summary', 'source_inventories', 'v3_references'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bootstrap_identity(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'canonical bootstrap source required')
    item = path.lstat()
    require(stat.S_ISREG(item.st_mode) and item.st_nlink == 1 and item.st_size <= 1048576,
        'bounded single-link bootstrap source required')
    return item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink


def validate_plan(plan, manifest):
    require(type(manifest) is dict and set(manifest) == FIELDS
        and manifest['schema'] == 'retained-dual-bank-parent-reconciliation-manifest/v1'
        and type(manifest['inputs']) is dict and manifest['inputs']
        and type(manifest['extensions']) is dict and set(manifest['source_inventories']) == {'control', 'balanced'},
        'closed read-only retained reconciliation manifest required')
    require(type(plan) is dict and set(plan) == set(PROFILE) | {'input_sha256'}
        and all(type(plan[k]) is type(v) and plan[k] == v for k, v in PROFILE.items())
        and plan['input_sha256'] == manifest['inputs'], 'fixed parent-only reconciliation profile required')


def panel_census(summary, arm):
    require(summary['complete'] is True and type(summary['panels']) is list,
        'complete saved evaluation summary required')
    rows = [p for p in summary['panels'] if p['arm'] == arm]
    expected = {(role, cohort) for role in ROLES for cohort in COHORTS}
    require(len(rows) == 8 and {(r['role'], r['cohort']) for r in rows} == expected,
        'exact selected/last four-cohort saved census required')
    return {(r['role'], r['cohort']): r for r in rows}


def checkpoint_join(state, ref, run, report, role, parent):
    expected = report['selected_weights_sha256' if role == 'selected' else 'last_complete_attempt_weights_sha256']
    require(state['role'] == role and type(state['dimension']) is int and state['dimension'] == 384
        and state['schema'] == parent['schema'] and state['recipe'] == run['recipe']
        and type(state['selected']) is bool and (role != 'selected' or state['selected'] is True)
        and state['tensor_sha256'] == ref['tensor_sha256'] == expected
        and digest(state['model_state']) == state['weights_sha256']
        and all(state[k] is False for k in ('qualified', 'admitted', 'proof_authority', 'source_semantics_verified')),
        'saved exact arm/role/width/report tensor join required')
    for key in ('codec', 'input_transform', 'initializer_receipt', 'lineage', 'architecture'):
        require(digest(state[key]) == digest(parent[key]), 'saved original context differs: ' + key)


def per_case_diff(baseline, candidate):
    require([r['id'] for r in baseline['formula_rows']] == [r['id'] for r in candidate['formula_rows']],
        'per-case identity census differs')
    lost, gained, stable_right, stable_wrong = [], [], 0, 0
    for old, new in zip(baseline['formula_rows'], candidate['formula_rows']):
        a, b = old['counts']['ordered_exact'], new['counts']['ordered_exact']
        require(type(a) is int and a in (0, 1) and type(b) is int and b in (0, 1), 'typed per-case exact flags required')
        if a == 1 and b == 0: lost.append(new['id'])
        elif a == 0 and b == 1: gained.append(new['id'])
        elif a == b == 1: stable_right += 1
        else: stable_wrong += 1
    return dict(newly_wrong_ids=lost, newly_correct_ids=gained, both_correct=stable_right,
        both_wrong=stable_wrong, comparison_is_posthoc=True)


def verify_scalar_binding(scalar, trace, sources, refs, codec):
    """Bind genuine posthoc scalar evidence to this exact source rollout."""
    scored_rows = [dict(row, target_ids=reference['target_ids'])
        for row, reference in zip(sources['rows'], refs)]
    require(len(sources['rows']) == len(refs) == 48
        and [r['id'] for r in sources['rows']] == [r['id'] for r in refs]
        and scalar['score_sha256'] == digest({k: v for k, v in scalar.items() if k != 'score_sha256'})
        and scalar['trace_sha256'] == trace['trace_sha256']
        and scalar['model_tensor_sha256'] == trace['model_tensor_sha256']
        and scalar['codec_sha256'] == trace['codec_sha256'] == digest(codec)
        and scalar['source_contexts_sha256'] == trace['source_contexts_sha256'] == digest(sources['source_contexts'])
        and scalar['references_sha256'] == digest(refs)
        and scalar['rows_sha256'] == digest(scored_rows),
        'saved scalar score/trace/tensor/codec/source/target binding differs')


def reused_panel(helper, record, sources, refs, state_ref, codec, transform, read_ref):
    require(record['state_ref'] == state_ref, 'saved panel checkpoint binding differs')
    trace = read_ref(record['trace_ref'])
    predictions = read_ref(record['predictions_ref'])
    fidelity = read_ref(record['formula_fidelity_ref'])
    scalar = read_ref(record['scalar_score_ref'])
    stored_join = read_ref(record['scalar_formula_join_ref'])
    helper.verify_trace(trace, sources['rows'], sources['source_contexts'], state_ref, codec, transform)
    require(predictions['predictions'] == trace['predictions'], 'saved raw trace/prediction join differs')
    verify_scalar_binding(scalar, trace, sources, refs, codec)
    joined = helper.join_scalar_formula(scalar, fidelity, refs)
    require(all(digest(joined[k]) == digest(stored_join[k]) for k in ('rows', 'per_field', 'extra_generated_unavailable_sites')),
        'genuine saved scalar/formula join differs')
    panel = helper.build_gate_panel(trace, fidelity, joined, sources['rows'], sources['source_contexts'], refs, codec)
    require(digest(panel['formula_metrics']) == digest(record['formula_metrics'])
        and digest(panel['seven_facets']) == digest(record['seven_facets'])
        and digest(panel['scalar_by_field']) == digest(record['scalar_by_field']), 'saved panel summary differs from complete rows')
    return panel


def execute(args):
    require(args.phase == 'evaluation', 'explicit read-only evaluation phase required')
    started = time.monotonic()
    deadline = started + PROFILE['max_seconds_total']
    raw_manifest = args.manifest.read_bytes()
    manifest = json.loads(raw_manifest)
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan, manifest)
    helper_path = Path(manifest['evaluation_helper_source'])
    helper_identity = bootstrap_identity(helper_path)
    require(manifest['inputs'].get(str(helper_path)) == hashlib.sha256(helper_path.read_bytes()).hexdigest(),
        'frozen helper bytes absent from reconciliation seal')
    helper = load_module(helper_path, '_retained_reconciliation_frozen_metric_helpers')
    require(bootstrap_identity(helper_path) == helper_identity
        and hashlib.sha256(helper_path.read_bytes()).hexdigest() == manifest['inputs'][str(helper_path)],
        'bootstrap source changed across import')
    pins = dict(manifest['inputs'])
    pins[str(args.manifest.resolve())] = hashlib.sha256(raw_manifest).hexdigest()
    pins[str(args.plan.resolve())] = manifest['plan_sha256']
    for relative, wanted in manifest['extensions'].items():
        rel = Path(relative)
        require(not rel.is_absolute() and '..' not in rel.parts, 'closed copied extension locator required')
        path = str((args.extension_root / rel).resolve(strict=True))
        require(path not in pins or pins[path] == wanted, 'conflicting copied extension pin')
        pins[path] = wanted
    witnesses = {path: helper._capture(path, wanted) for path, wanted in pins.items()}
    ctx, owners = None, {}
    def fence():
        require(time.monotonic() < deadline, 'read-only reconciliation deadline')
        for path, wanted in pins.items():
            require(helper._capture(path, wanted) == witnesses[path], 'reconciliation byte/identity drift')
        if ctx is not None: numeric.fence(ctx)
        for name, owner in owners.items():
            require(helper._current_owner(args.dependency_root, name) is owner, 'reconciliation loaded origin drift')
        for path, witness in witnesses.items():
            require(helper._file_identity(path) == witness, 'closing reconciliation cross-owner identity drift')
    def read(path):
        path = str(Path(path).resolve(strict=True))
        require(path in pins and helper._capture(path, pins[path]) == witnesses[path], 'unsealed retained input')
        payload = Path(path).read_bytes()
        require(hashlib.sha256(payload).hexdigest() == pins[path], 'retained JSON bytes drifted at read')
        return json.loads(payload)
    def read_ref(ref):
        path = str(Path(ref['path']).resolve(strict=True))
        require(type(ref['bytes']) is int and ref['bytes'] == Path(path).stat().st_size
            and pins.get(path) == ref['sha256'], 'exact saved artifact reference required')
        return read(path)
    fence()
    require(not args.output.exists(), 'fresh owned reconciliation output required')
    numeric_path = Path(manifest['numeric_source'])
    require(str(numeric_path) in pins, 'sealed current numerical metadata owner required')
    numeric = helper._load_pinned_module(numeric_path, pins[str(numeric_path)], '_retained_parent_numeric_owner')
    sys.meta_path.insert(0, numeric.ForbiddenImports())
    sys.addaudithook(numeric.audit)
    previous = SimpleNamespace(**vars(args))
    previous.phase, previous.dimension = 'preflight', 384
    previous.manifest, previous.plan = Path(manifest['initialization_manifest']), Path(manifest['initialization_plan'])
    previous.extension_root = Path(manifest['initialization_extension_root'])
    ctx = numeric.load_context(previous, deadline=deadline)
    require(Path(ctx['manifest']['current_source_root']).resolve() == args.dependency_root.resolve()
        and all(pins.get(path) == wanted for path, wanted in ctx['pins'].items()),
        'complete original/current authenticated context closure required')
    for name in ('generated_scalar_observation', 'decoder_source_fidelity', 'clause_source_context'):
        owners[name] = helper._current_owner(args.dependency_root, name)
        require(str(Path(owners[name].__file__)) in pins, 'current reconciliation owner absent from seal')
    scalar_owner, fidelity_owner = owners['generated_scalar_observation'], owners['decoder_source_fidelity']
    codec, transform = ctx['donor']['codec'], ctx['donor']['input_transform']
    inventories = {role: read(path) for role, path in manifest['source_inventories'].items()}
    require(all(digest(inventories[role]) == digest(ctx['inventories'][role]) for role in inventories),
        'unchanged original control13/balanced16 envelopes required')
    cohorts = helper.prepare_cohorts(dict(rows=ctx['rows'], source_contexts=ctx['source_contexts'], donor=ctx['donor']),
        inventories['control'], inventories['balanced'], owners['clause_source_context'])
    parallel_training = read(manifest['parallel_training_summary'])
    parallel_evaluation = read(manifest['parallel_evaluation_summary'])
    require(parallel_training['complete'] is True and parallel_training['fits'] == 1
        and len(parallel_training['runs']) == 1 and parallel_training['parent_tensor_sha256'] == PARENT_TENSOR,
        'one existing original-parent dual fit required')
    dual_run = read_ref(parallel_training['runs'][0])
    dual_report = read_ref(dual_run['training_ref'])
    require(dual_run['arm'] == PARALLEL_ARM and dual_run['parent_state']['tensor_sha256'] == PARENT_TENSOR,
        'preserved original parallel arm/parent identities required')
    control_training = read(manifest['archived_control_training_summary'])
    control_runs = [read_ref(ref) for ref in control_training['runs']]
    control_runs = [r for r in control_runs if r['arm'] == CONTROL_ARM]
    require(len(control_runs) == 1, 'one original archived control required')
    control_run = control_runs[0]
    control_report = read_ref(control_run['training_ref'])
    for run, report in ((dual_run, dual_report), (control_run, control_report)):
        require(run['parent_state']['tensor_sha256'] == PARENT_TENSOR and run['budget_completed'] is True
            and type(report['optimizer_steps']) is int and report['optimizer_steps'] == 170
            and report['stopped_reason'] == 'epochs_completed' and report['config']['max_optimizer_steps'] == 1000,
            'preserved natural170/1000-cap retained fit required')
        for role in ROLES:
            checkpoint_join(read_ref(run['states'][role]), run['states'][role], run, report, role, ctx['restore_packet']['checkpoint'])
    saved_censuses = {'dual': panel_census(parallel_evaluation, PARALLEL_ARM),
        'archived_control': panel_census(read(manifest['archived_control_evaluation_summary']), CONTROL_ARM)}
    bank_metrics, bank_refs = {}, {}
    for name, refs in [('parent', parallel_training['source_bank_readouts'])] + [
        (kind + ':' + role, run['full180_postfit_readouts'][role])
        for kind, run in (('dual', dual_run), ('archived_control', control_run)) for role in ROLES]:
        tensor = PARENT_TENSOR if name == 'parent' else (dual_run if name.startswith('dual:') else control_run)['states'][name.split(':')[1]]['tensor_sha256']
        bank_metrics[name] = {role: helper.verified_bank_metrics(read_ref(ref), ctx['banks_by_role'][role], codec, tensor)
            for role, ref in refs.items()}
        require(set(bank_metrics[name]) == {'control', 'balanced'}, 'both complete180 banks required')
        bank_refs[name] = deepcopy(refs)
    helper.forbid_evaluation_training(ctx)
    fence()
    args.output.mkdir(parents=True)
    save = helper.compact_writer(args.output, PROFILE['output_payload_cap_bytes'])
    helper.durable(save, args.output / 'sealed-recipe.json', dict(manifest=manifest, plan=plan, **FALSE))
    model = numeric.restore_parent(ctx)
    require(ctx['core'].tensor_digest(model) == PARENT_TENSOR, 'restored exact original parent differs')
    fresh = {}
    for cohort, sources in cohorts.items():
        fence()
        trace = scalar_owner.collect_source_scalar_trace(model, sources['rows'], codec=codec,
            input_transform=transform, source_contexts=sources['source_contexts'], max_target_tokens=512,
            batch_size=8, deadline=min(deadline, time.monotonic() + 60.), max_memory_bytes=PROFILE['max_trace_memory_bytes'])
        helper.verify_trace(trace, sources['rows'], sources['source_contexts'],
            ctx['parent_summary']['states']['selected'], codec, transform)
        trace_ref = helper.durable(save, args.output / 'parent' / cohort / 'source-head-trace.json', trace)
        pred_ref = helper.durable(save, args.output / 'parent' / cohort / 'actual-predictions.json',
            dict(predictions=trace['predictions'], model_tensor_sha256=PARENT_TENSOR, complete=True,
                generation_reference_access=False, same_pass_scalar_trace_sha256=trace['trace_sha256'], **FALSE))
        fresh[cohort] = dict(trace_ref=trace_ref, predictions_ref=pred_ref, prediction_fsynced=True)
        del trace
    require(ctx['core'].tensor_digest(model) == PARENT_TENSOR and len(fresh) == 4, 'complete preserved parent generation required')
    del model
    fence()
    for value in fresh.values():
        require(helper.sha(value['trace_ref']['path']) == value['trace_ref']['sha256']
            and helper.sha(value['predictions_ref']['path']) == value['predictions_ref']['sha256'], 'parent durable barrier drift')
    helper.durable(save, args.output / 'parent-predictions-complete.json', dict(records=fresh,
        complete=True, new_physical_panels=4, explicit_v3_reference_json_loaded=False,
        original_TRAIN_validation_metadata_already_known=True, **FALSE))
    reference_sets = dict(original_train48=helper.original_train_references(ctx['rows']['train'], codec),
        normative_train48=inventories['control']['corpus']['references'],
        new_balanced_train48=inventories['balanced']['corpus']['references'], exposed_v3_48=read(manifest['v3_references']))
    refs = {name: helper.bind_references(cohorts[name]['rows'], values, codec) for name, values in reference_sets.items()}
    panels, records = {}, []
    for cohort, files in fresh.items():
        payloads = {}
        for key in ('trace_ref', 'predictions_ref'):
            ref = files[key]
            raw = Path(ref['path']).read_bytes()
            require(len(raw) == ref['bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256'],
                'fresh parent evidence drifted after reference barrier')
            payloads[key] = json.loads(raw)
        trace = payloads['trace_ref']
        source = cohorts[cohort]
        helper.verify_trace(trace, source['rows'], source['source_contexts'],
            ctx['parent_summary']['states']['selected'], codec, transform)
        require(payloads['predictions_ref']['predictions'] == trace['predictions'],
            'fresh parent raw trace/prediction join differs')
        scored_rows = [dict(row, target_ids=ref['target_ids']) for row, ref in zip(source['rows'], refs[cohort])]
        scalar = scalar_owner.score_scalar_trace(trace, scored_rows, refs[cohort],
            split='exposed_development' if cohort == 'exposed_v3_48' else 'training', codec=codec,
            input_transform=transform, source_contexts=source['source_contexts'], validate_rule=ctx['validate_rule'], deadline=deadline)
        verify_scalar_binding(scalar, trace, source, refs[cohort], codec)
        fidelity = fidelity_owner.score_predictions(refs[cohort], trace['predictions'], codec=codec,
            validate_rule=ctx['validate_rule'], output_limit=512, validator_id=ctx['validator_id'])
        joined = helper.join_scalar_formula(scalar, fidelity, refs[cohort])
        panel = helper.build_gate_panel(trace, fidelity, joined, source['rows'], source['source_contexts'], refs[cohort], codec)
        evidence = {key: helper.durable(save, args.output / 'parent' / cohort / filename, value)
            for key, filename, value in (('scalar_ref', 'posthoc-scalar-score.json', scalar),
                ('fidelity_ref', 'actual-formula-fidelity.json', fidelity), ('join_ref', 'scalar-formula-join.json', joined),
                ('panel_ref', 'retention-panel.json', panel))}
        panels[('parent', 'selected', cohort)] = panel
        records.append(dict(endpoint='parent', role='selected', cohort=cohort, newly_generated=True,
            **files, **evidence, formula_metrics=panel['formula_metrics'], **FALSE))
        fence()
    for kind, census in saved_censuses.items():
        run = dual_run if kind == 'dual' else control_run
        for (role, cohort), old_record in census.items():
            panel = reused_panel(helper, old_record, cohorts[cohort], refs[cohort], run['states'][role], codec, transform, read_ref)
            panel_ref = helper.durable(save, args.output / kind / role / cohort / 'retention-panel.json', panel)
            panels[(kind, role, cohort)] = panel
            records.append(dict(endpoint=kind, role=role, cohort=cohort, newly_generated=False,
                original_saved_record=deepcopy(old_record), panel_ref=panel_ref, formula_metrics=panel['formula_metrics'], **FALSE))
            fence()
    expected = {name: helper.complete_bindings(cohorts[name]['rows'], cohorts[name]['source_contexts'], refs[name], codec)
        for name in TRAIN_COHORTS}
    baseline = {name: panels[('parent', 'selected', name)] for name in TRAIN_COHORTS}
    gates = []
    for kind in saved_censuses:
        for role in ROLES:
            candidate = {name: panels[(kind, role, name)] for name in TRAIN_COHORTS}
            gate = ctx['dual_owner'].retention.retention_gate(schedule=ctx['dual_prepared_banks'].schedule,
                expected_bindings=expected, baseline_panels=baseline, candidate_panels=candidate,
                baseline_bank_fields=bank_metrics['parent'], candidate_bank_fields=bank_metrics[kind + ':' + role])
            differences = {name: per_case_diff(panels[('parent', 'selected', name)], panels[(kind, role, name)]) for name in COHORTS}
            gates.append(dict(endpoint=kind, role=role, baseline_tensor_sha256=PARENT_TENSOR,
                gate=gate, per_case_parent_comparison=differences, exposed_v3_selects=False))
    v3_pair = per_case_diff(panels[('archived_control', 'selected', 'exposed_v3_48')], panels[('dual', 'selected', 'exposed_v3_48')])
    fence()
    result = dict(PROFILE, complete=True, models_executed=True, elapsed_seconds=time.monotonic() - started,
        panels=records, parent_retention_gates=gates, source_bank_metrics=bank_metrics,
        source_bank_original_refs=bank_refs, archived_control_vs_dual_v3=v3_pair,
        candidate_state_refs=dict(dual=dual_run['states'], archived_control=control_run['states']),
        explicit_v3_reference_bytes_hashed_before_generation=True, source_only_new_predictions=True,
        new_encoder_or_embedding_generation=False, original_saved_candidates_and_quotas_unchanged=True,
        saved_paragraph_vector_producer_authenticated=False,
        interpretation='One preexisting dual fit and archived controls; original-parent gate, not matched causal or legal qualification.')
    return helper.durable(save, args.output / 'summary.json', result)


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['evaluation'], required=True)
    for name in ('dependency-root', 'extension-root', 'manifest', 'plan', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.dependency_root.resolve()))
    print(json.dumps(execute(args), sort_keys=True))


if __name__ == '__main__':
    main()

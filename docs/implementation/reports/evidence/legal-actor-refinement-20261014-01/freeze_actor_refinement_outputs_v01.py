"""Qualify future actor-refinement runtime metadata and freeze opaque results before scoring."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('actor_metadata_runner', F / 'run_actor_refinement_v01.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
PUBLIC_RUNTIME = ('pre-admission.json', 'scheduler-adoption.json', 'lease-binding.json', 'command.json',
    'child-identity.json', 'resource-observations.json', 'child-exit.json', 'group-rss-summary.json',
    'owned-group-final.json', 'guardian-exit.json', 'lease-observations.jsonl', 'group-rss-observations.jsonl', 'child.log')


def expected_names():
    names = {'data-schedule-before-models.json', 'cell-checkpoint.json', 'cell-training.json', 'summary.json',
        'initial-parent-head-parity.json', 'trained-frozen-head-retention.json'}
    for stage in ('baseline', 'trained'):
        names.update(f'{stage}-{panel}-{kind}.json' for panel in r.PANELS for kind in ('raw', 'joint'))
    for label in ('initial-training168', 'parent-training168', 'trained-training168', 'parent-fresh_dev',
                  'parent-fresh_test'):
        names.update(label + '-' + kind + '.json' for kind in ('raw', 'joint'))
    for stage in ('initial', 'trained'):
        names.add(stage + '-parity.json')
        names.update(stage + '-parity-' + c + '.json' for c in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    r.require(len(names) == 62, 'Exact62 output geometry required')
    return names


def qualify_training_summary(plan,summary,report):
    legacy = r.legacy_runner(); retained = legacy.prior_runner(); helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder()); helper.bootstrap(Path(plan['package_root']))
    r.qualify_actor_trace(report)
    names=['actor_start.weight','actor_start.bias','actor_end.weight','actor_end.bias','actor_attention.query','actor_context.gate']
    r.require(summary['schema']=='actor-refinement-cell-results/v1' and summary['status']=='completed'
        and summary['cell']==r.CELL and summary['attempt_name']==r.ATTEMPT and summary['actual_new_updates']==32
        and summary['successful_output_file_count']==62 and summary['actual_external_encoder_calls']==0 and summary['latent_enabled'] is False
        and len(summary['opening_owners'])==plan['expected_loaded_owner_count']==16 and summary['opening_owners']==summary['closing_owners']
        and all(plan['source_owner_pins'].get(name)==value for name,value in summary['opening_owners'].items())
        and {'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'+name for name in ('legal_span_formula','legal_span_continuation',
            'legal_span_targeted_loss','legal_span_split_features','legal_span_actor_boundary','legal_span_actor_features','legal_span_conditions_presence','legal_span_actor_refinement')}<=set(summary['opening_owners']),
        'Exact completed source-only16/8 envelope required')
    r.require(report['schema']=='bounded-actor-refinement-adapter-training/v1' and report['optimizer_steps']==32 and report['stopped_reason']=='step_limit'
        and report['training_policy']['objective']==r.CELL and report['optimizer_parameter_order']==names
        and report['checkpoint_sha256']==summary['checkpoint']['sha256'] and report['final_model_state_sha256']==summary['final_model_state_sha256']
        and report['source_conditions_presence_checkpoint_sha256']==summary['source_checkpoint']['sha256']==r.SOURCE_SHA
        and report['source_conditions_presence_model_state_sha256']==summary['source_model_state_sha256']==r.SOURCE_STATE_SHA
        and report['source_conditions_presence_optimizer_steps']==summary['source_optimizer_steps']==32
        and summary['fresh_Adam'] is True and summary['inherited_optimizer_moments'] is False
        and summary['candidate_training_capture_call_sizes']==summary['parent_training_capture_call_sizes']==[128,40],
        'Exact trainedN11 parent and fresh six-tensor actor Adam required')
    batches=report['batch_trace'];schedule=summary['prepared_schedule']
    r.require(batches['completed_updates']==32 and batches['training_count']==168 and batches['training_manifest_sha256']==plan['training_manifest_sha256']
        and [b['indices'] for b in batches['batches']]==schedule['batch_indices'] and [b['ids'] for b in batches['batches']]==schedule['batch_ids']
        and [b['loss'] for b in batches['batches']]==report['batch_losses'],'Exact32/168 source schedule trace required')
    expected={'total_inference_source_forwards':1280,'actual_training_model_forwards':32,'total_actual_model_forwards':1312,
        'training_batch_source_occurrences':384,'total_model_source_occurrences':1664,'candidate_conditions_presence_inference_calls':1280,
        'actual_conditions_presence_head_calls':1312,'reused_parent_capture_file_count':6,'reused_parent_capture_rows':240,'new_parent_control_forwards':0,
        'candidate_diagnostic_source_forwards':928,'candidate_training_capture_source_forwards':336,'dormant_control_source_forwards':16,'parent_extra_source_forwards':0,
        'feature_paths_per_source_forward':3}
    r.require(all(type(summary[k]) is int and summary[k]==value for k,value in expected.items()),'Actual new-forward/copy accounting differs')
    copies={'parent-training168':'training168','parent-fresh_dev':'fresh_dev','parent-fresh_test':'fresh_test'}
    r.require(summary['reused_parent_captures']=={label:plan['source_reference_panels'][panel] for label,panel in copies.items()},'All six reused saved parent captures require exact provenance')


def qualify_gates(initial,final):
    r.require(initial['schema']=='actor-refinement-initial-parent-parity/v1' and final['schema']=='actor-refinement-frozen-head-retention/v1'
        and initial['source_rows']==final['source_rows']==632 and initial['all_compared_components_bit_equal'] is True
        and final['all_compared_components_bit_equal'] is True and initial['optimizer_updates_before_gate']==0
        and final['compared_all_boundaries'] is False and final['compared_conditions_presence'] is True
        and final['compared_nonactor_boundaries'] is True and final['compared_actor_boundaries'] is False
        and final['compared_other_three_presence'] is True and final['compared_modality'] is True,'Mandatory actual632 initial/final protected gates required')
    for value in (initial,final):
        r.require(set(value['rows'])=={*r.PANELS,'training168'} and all(len(value['rows'][name])==(168 if name=='training168' else r.COUNTS[name])
            for name in value['rows']) and sum(map(len,value['rows'].values()))==632,'Complete all632 per-source parity coverage required')


def main():
    artifacts = {}
    def bind(path, expected=None):
        p = Path(path); r.require('private-runtime-snapshots' not in p.parts and p.name not in
            {'resources-start.json', 'resources-final.json', 'disk-reservations.json'}, 'Private resource bodies remain unopened')
        v = r.pin(p); r.require(expected is None or v == expected, 'Saved public identity differs')
        brief = {k: v[k] for k in ('bytes', 'sha256')}
        r.require(str(p) not in artifacts or artifacts[str(p)] == brief, 'Conflicting runtime artifact identity')
        artifacts[str(p)] = brief; return v
    def read(path, expected=None):
        r.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name, 'Model/reference parsing prohibited')
        v = bind(path, expected); return r.read(path, v)
    approval_path = F / 'runtime-freeze-source-independent-review-v01.json'
    approval = read(approval_path)
    own = bind(Path(__file__).resolve())
    r.require(approval['schema'] == 'actor-refinement-runtime-freeze-source-independent-review/v1'
              and approval['passed'] is True and approval['findings'] == [] and approval['observer'] == own, 'Exact source qualification required')
    for path, expected in approval['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == {k: expected[k] for k in ('bytes', 'sha256')}, 'Source qualification drift')
    plan_pin = bind(F / (r.CELL + '-plan-v01.json')); plan = read(plan_pin['path'], plan_pin); r.validate_plan(plan)
    training_review_pin = bind(F / (r.CELL + '-training-review-v01.json')); training_review = read(training_review_pin['path'], training_review_pin)
    r.require(training_review['schema']=='actor-refinement-concrete-training-independent-review/v1' and training_review['passed'] is True and training_review['findings'] == [] and training_review['phase'] == 'training'
              and training_review['plan_sha256'] == plan_pin['sha256'], 'Actual training qualification required')
    for path, expected in plan['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == expected, 'Actual admitted source drift')
    r.require(len(plan['source_owner_pins']) == 39 and all(
        plan['artifacts'].get(value['path']) == {k: value[k] for k in ('bytes', 'sha256')}
        for value in plan['source_owner_pins'].values()), 'All39 plan source owners must join raw admitted closure')
    baseline_ledger = r.qualify_resource_baseline(plan)
    resource_pin = bind(F / (r.CELL + '-terminal-resource-audit-v01.json')); resource = read(resource_pin['path'], resource_pin)
    r.require(resource['schema'] == 'actor-refinement-terminal-resource-audit/v1' and resource['passed'] is True
              and resource['findings'] == [] and resource['preserved_prior_record_count'] == baseline_ledger['record_count']
              and resource['closing_record_count'] >= baseline_ledger['record_count'] + 1 and resource['only_new_own_claim']['status'] == 'released'
              and resource['failed_N7_claim_retained_and_fully_charged'] is True
              and resource['failed_N8_claim_explicitly_reconciled'] is True
              and resource['own_scheduler_lease_absent'] is True
              and type(resource['scheduler_lease_count']) is int and resource['scheduler_lease_count'] >= 0
              and type(resource['scheduler_waiter_count']) is int and resource['scheduler_waiter_count'] >= 0, 'Conserved successful resource closure required')
    r.require(resource['plan'] == plan_pin and resource['training_review'] == training_review_pin,
              'Terminal resource qualification must join the actual plan and training review')
    resource_source = read(F / 'actor-refinement-terminal-resource-source-independent-review-v01.json')
    r.require(resource_source['schema'] == 'actor-refinement-terminal-resource-source-independent-review/v1'
              and resource_source['passed'] is True and resource_source['findings'] == []
              and resource['source_qualification'] == bind(F / 'actor-refinement-terminal-resource-source-independent-review-v01.json')
              and resource['observer'] == resource_source['observer'] == bind(F / 'audit_actor_refinement_terminal_resources_v01.py'),
              'Terminal observer and its exact independent qualification must join')
    for path, expected in resource['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == {k: expected[k] for k in ('bytes', 'sha256')},
                  'Terminal qualified public wrapper/source identity drift')
    resource_inputs_pin = bind(F / 'actor-refinement-terminal-resource-inputs-v01.json')
    r.require(resource['input_manifest'] == resource_inputs_pin, 'Terminal exact input manifest differs')
    resource_inputs = read(resource_inputs_pin['path'], resource_inputs_pin)
    r.require(resource_inputs['plan'] == plan_pin and resource_inputs['training_review'] == training_review_pin,
              'Terminal manifest plan and training review must join')
    attempt = r.RUN_ROOT / r.ATTEMPT; root = attempt / 'results'
    all_paths = list(root.rglob('*'))
    r.require(not any(p.is_symlink() or not p.is_file() for p in all_paths)
              and {p.name for p in all_paths} == expected_names() and len(all_paths) == 62, 'Exact flat62 result inventory required')
    results = {str(p): {k: bind(p)[k] for k in ('bytes', 'sha256')} for p in sorted(all_paths)}
    r.require(sum(v['bytes'] for v in results.values()) <= 200000000, 'Own result byte bound exceeded')
    summary_pin = bind(root / 'summary.json'); summary = read(summary_pin['path'], summary_pin)
    for key, name in [('checkpoint', 'cell-checkpoint.json'), ('training', 'cell-training.json'), ('schedule', 'data-schedule-before-models.json'),
                      ('initial_parent_head_parity', 'initial-parent-head-parity.json'),
                      ('frozen_head_retention', 'trained-frozen-head-retention.json')]:
        r.require(summary[key] == bind(root / name), 'Summary descriptor must join its exact frozen local result')
    for key, stage in [('baseline_panels', 'baseline'), ('diagnostics', 'trained'), ('parent_fresh_panels', 'parent')]:
        expected_panels = r.FRESH_PANELS if key == 'parent_fresh_panels' else r.PANELS
        r.require(set(summary[key]) == set(expected_panels), 'Complete exact panel summary map required')
        for panel in expected_panels:
            pair = summary[key][panel]
            r.require(set(pair) == {'raw', 'joint', 'row_count'} and pair['row_count'] == r.COUNTS[panel],
                      'Closed exact capture pair required')
            for view in ('raw', 'joint'):
                r.require(pair[view] == bind(root / (stage + '-' + panel + '-' + view + '.json')),
                          'Capture descriptor must join exact frozen local filename')
    for key, label in [('initial_training_capture', 'initial-training168'), ('parent_training_capture', 'parent-training168'),
                       ('final_training_capture', 'trained-training168')]:
        pair = summary[key]
        r.require(set(pair) == {'raw', 'joint', 'row_count'} and pair['row_count'] == 168, 'Exact training168 capture pair required')
        for view in ('raw', 'joint'):
            r.require(pair[view] == bind(root / (label + '-' + view + '.json')), 'Exact frozen training capture filename required')
    for label,panel in (('parent-training168','training168'),('parent-fresh_dev','fresh_dev'),('parent-fresh_test','fresh_test')):
        for view in ('raw','joint'):
            source=plan['source_reference_panels'][panel][view];local=bind(root/(label+'-'+view+'.json'))
            r.require(bind(source['path'],source)==source and all(local[k]==source[k] for k in ('bytes','sha256')),
                'Reused saved N11 capture bytes must remain exact and contribute zero new forwards')
    for key, stage in [('initial_parity', 'initial'), ('trained_parity', 'trained')]:
        r.require(summary[key] == bind(root / (stage + '-parity.json')), 'Exact dormant parity receipt required')
        parity = read(summary[key]['path'], summary[key])
        r.require(parity['passed'] is True and parity['source_model_forwards'] == 8
                  and parity['score_and_greedy_decisions_bit_equal'] is True
                  and parity['genuine_latent_semantics_tested'] is False
                  and [c['name'] for c in parity['controls']] == ['zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'],
                  'Complete dormant placeholder metadata required')
        for control in parity['controls']:
            r.require(control['report'] == bind(root / (stage + '-parity-' + control['name'] + '.json')),
                      'Dormant descriptor must join exact frozen local filename')
    schedule_metadata = read(summary['schedule']['path'], summary['schedule'])
    r.require(schedule_metadata['schedule'] == summary['prepared_schedule'] and schedule_metadata['training_count'] == 168
              and schedule_metadata['model_imported'] is False, 'Source schedule must be frozen before numerical import')
    report = read(summary['training']['path'], summary['training'])
    qualify_training_summary(plan, summary, report)
    initial = read(summary['initial_parent_head_parity']['path'], summary['initial_parent_head_parity'])
    final = read(summary['frozen_head_retention']['path'], summary['frozen_head_retention'])
    qualify_gates(initial, final)
    for name in PUBLIC_RUNTIME: bind(attempt / name)
    pre = read(attempt / 'pre-admission.json'); terminal_pin = bind(attempt / 'guardian-exit.json'); terminal = read(terminal_pin['path'], terminal_pin)
    r.require(pre['plan'] == plan_pin and pre['review'] == training_review_pin
              and pre['runner'] == bind(F / 'run_actor_refinement_v01.py') and pre['guardian'] == bind(F / 'run_scope_guardian_v02.py'), 'Actual admission source custody differs')
    r.require(terminal['returncode'] == terminal['child_returncode'] == 0 and terminal['artifacts_durable'] is True
              and terminal['resource_reservation_released'] is True, 'Durable released actual guardian success required')
    for path, expected in artifacts.items():
        r.require({k: r.pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Closing full public runtime pin drift')
    for path in all_paths:
        path.chmod(0o444)
        with path.open('rb') as f: os.fsync(f.fileno())
    runtime_path = F / 'actor-refinement-ce-runtime-review-v01.json'
    runtime_pin = r.write(runtime_path, dict(schema='actor-refinement-runtime-independent-review/v1', passed=True, findings=[],
        observer=own, independent_source_review=bind(approval_path), artifacts=artifacts, plan=plan_pin, training_review=training_review_pin,
        resource_review=resource_pin, actual_returned_optimizer_updates=32,
        actual_model_forwards=1312, actual_inference_source_forwards=1280, actual_training_source_occurrences=384,
        actual_total_source_occurrences=1664, candidate_conditions_presence_inference_calls=1280,
        actual_conditions_presence_head_calls=1312, reused_parent_capture_file_count=6, reused_parent_capture_rows=240, new_parent_control_forwards=0, initial_source_rows=632, final_source_rows=632, outputs=results, output_file_count=62,
        successful_output_file_count=62,
        checkpoint_JSON_parses=0, model_or_encoder_calls=0, private_global_body_reads=0, semantic_accuracy=None, default_promotion=False))
    runtime_path.chmod(0o444)
    freeze_path = F / 'actor-refinement-output-freeze-v01.json'
    freeze_pin = r.write(freeze_path, dict(schema='actor-refinement-output-freeze/v1', all_outputs_frozen=True,
        authorizes_authored_eval_scoring=True, evaluation_contract=plan['evaluation_contract'], plan=plan_pin, summary=summary_pin,
        guardian_terminal=terminal_pin, runtime_review=runtime_pin, results=results, actual_returned_optimizer_updates=32,
        model_or_encoder_calls=0, checkpoint_JSON_parses=0,
        statutory_reference_scoring_authorized=False, semantic_accuracy=None, default_promotion=False))
    freeze_path.chmod(0o444)
    print(freeze_pin)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args(); main()

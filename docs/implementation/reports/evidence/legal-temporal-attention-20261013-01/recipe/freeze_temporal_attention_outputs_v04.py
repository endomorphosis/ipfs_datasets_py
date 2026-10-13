"""Qualify saved N7 runtime metadata and freeze opaque results before scoring."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

F = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('attention_metadata_runner', F / 'run_temporal_attention_v02.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
PUBLIC_RUNTIME = ('pre-admission.json', 'scheduler-adoption.json', 'lease-binding.json', 'command.json',
    'child-identity.json', 'resource-observations.json', 'child-exit.json', 'group-rss-summary.json',
    'owned-group-final.json', 'guardian-exit.json', 'lease-observations.jsonl', 'group-rss-observations.jsonl', 'child.log')


def expected_names():
    names = {'data-schedule-before-models.json', 'cell-checkpoint.json', 'cell-training.json', 'summary.json',
        'initial-parent-head-parity.json', 'trained-frozen-head-retention.json',
        'uniform-protected-head-retention.json', 'historical-control-protected-head-retention.json'}
    for stage in ('baseline', 'trained'):
        names.update(f'{stage}-{panel}-{kind}.json' for panel in r.PANELS for kind in ('raw', 'joint'))
    for label in ('initial-training168', 'parent-training168', 'trained-training168', 'parent-fresh_dev',
                  'parent-fresh_test', 'uniform-old_tune', 'uniform-fresh_dev', 'uniform-fresh_test',
                  'historical-control-fresh_dev', 'historical-control-fresh_test'):
        names.update(label + '-' + kind + '.json' for kind in ('raw', 'joint'))
    for stage in ('initial', 'trained'):
        names.add(stage + '-parity.json')
        names.update(stage + '-parity-' + c + '.json' for c in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    r.require(len(names) == 74, 'Exact74 output geometry required')
    return names


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
    approval_path = F / 'runtime-freeze-source-independent-review-v04.json'
    approval = read(approval_path)
    own = bind(Path(__file__).resolve())
    r.require(approval['schema'] == 'temporal-attention-runtime-freeze-source-independent-review/v1'
              and approval['passed'] is True and approval['findings'] == [] and approval['observer'] == own, 'Exact source qualification required')
    for path, expected in approval['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == {k: expected[k] for k in ('bytes', 'sha256')}, 'Source qualification drift')
    plan_pin = bind(F / (r.CELL + '-plan-v02.json')); plan = read(plan_pin['path'], plan_pin); r.validate_plan(plan)
    training_review_pin = bind(F / (r.CELL + '-training-review-v02.json')); training_review = read(training_review_pin['path'], training_review_pin)
    r.require(training_review['passed'] is True and training_review['findings'] == [] and training_review['phase'] == 'training'
              and training_review['plan_sha256'] == plan_pin['sha256'], 'Actual training qualification required')
    for path, expected in plan['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == expected, 'Actual admitted source drift')
    resource_pin = bind(F / (r.CELL + '-terminal-resource-audit-v03.json')); resource = read(resource_pin['path'], resource_pin)
    r.require(resource['schema'] == 'temporal-attention-terminal-resource-audit/v1' and resource['passed'] is True
              and resource['findings'] == [] and resource['preserved_prior_record_count'] == 532
              and resource['closing_record_count'] == 533 and resource['only_new_own_claim']['status'] == 'released'
              and resource['scheduler_lease_count'] == resource['scheduler_waiter_count'] == 0, 'Conserved successful resource closure required')
    r.require(resource['plan'] == plan_pin and resource['training_review'] == training_review_pin,
              'Terminal resource qualification must join the actual plan and training review')
    resource_source = read(F / 'attention-terminal-resource-source-independent-review-v03.json')
    r.require(resource_source['schema'] == 'temporal-attention-terminal-resource-source-independent-review/v1'
              and resource_source['passed'] is True and resource_source['findings'] == []
              and resource['source_qualification'] == bind(F / 'attention-terminal-resource-source-independent-review-v03.json')
              and resource['observer'] == resource_source['observer'] == bind(F / 'audit_attention_terminal_resources_v03.py'),
              'Terminal observer and its exact independent qualification must join')
    for path, expected in resource['artifacts'].items():
        r.require({k: bind(path)[k] for k in ('bytes', 'sha256')} == {k: expected[k] for k in ('bytes', 'sha256')},
                  'Terminal qualified public wrapper/source identity drift')
    resource_inputs_pin = bind(F / 'attention-terminal-resource-inputs-v03.json')
    r.require(resource['input_manifest'] == resource_inputs_pin, 'Terminal exact input manifest differs')
    resource_inputs = read(resource_inputs_pin['path'], resource_inputs_pin)
    r.require(resource_inputs['plan'] == plan_pin and resource_inputs['training_review'] == training_review_pin,
              'Terminal manifest plan and training review must join')
    attempt = r.RUN_ROOT / r.ATTEMPT; root = attempt / 'results'
    all_paths = list(root.rglob('*'))
    r.require(not any(p.is_symlink() or not p.is_file() for p in all_paths)
              and {p.name for p in all_paths} == expected_names() and len(all_paths) == 74, 'Exact flat74 result inventory required')
    results = {str(p): {k: bind(p)[k] for k in ('bytes', 'sha256')} for p in sorted(all_paths)}
    r.require(sum(v['bytes'] for v in results.values()) <= 200000000, 'Own result byte bound exceeded')
    summary_pin = bind(root / 'summary.json'); summary = read(summary_pin['path'], summary_pin)
    for key, name in [('checkpoint', 'cell-checkpoint.json'), ('training', 'cell-training.json'),
                      ('initial_parent_head_parity', 'initial-parent-head-parity.json'),
                      ('frozen_head_retention', 'trained-frozen-head-retention.json')]:
        r.require(summary[key] == bind(root / name), 'Summary descriptor must join its exact frozen local result')
    report = read(summary['training']['path'], summary['training']); partition = report['parameter_partition']
    r.require(summary['schema'] == 'temporal-attention-cell-results/v1' and summary['status'] == 'completed'
              and summary['cell'] == r.CELL and summary['attempt_name'] == r.ATTEMPT
              and summary['actual_new_updates'] == 32 and summary['actual_new_control_updates'] == 0
              and summary['actual_external_encoder_calls'] == 0 and summary['latent_enabled'] is False
              and summary['opening_owners'] == summary['closing_owners']
              and all(plan['source_owner_pins'].get(name) == value for name, value in summary['opening_owners'].items())
              and {'ipfs_datasets_py.optimizers.logic_theorem_optimizer.' + name for name in
                   ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss', 'legal_span_split_features',
                    'legal_span_temporal_adapter', 'legal_span_temporal_attention')} <= set(summary['opening_owners']), 'Exact completed source-only envelope required')
    r.require(report['schema'] == 'bounded-temporal-attention-adapter-training/v1' and report['optimizer_steps'] == 32
              and report['stopped_reason'] == 'step_limit' and len(partition['model_parameter_names']) == 37
              and len(partition['frozen_parameter_names']) == 34 and partition['active_trainable_scalar_count'] == 322
              and partition['trainable_parameter_names'] == ['temporal_attention.query', 'temporal_presence.weight', 'temporal_presence.bias'],
              'Exact completed37/34/3 training geometry required')
    r.require(report['frozen_base34_sha256_initial'] == report['frozen_base34_sha256_final'] == r.SOURCE_STATE_SHA
              and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final'], 'Frozen tensor digests changed')
    for key, n in [('total_inference_source_forwards', 1760), ('actual_training_model_forwards', 32),
                   ('total_actual_model_forwards', 1792), ('training_batch_source_occurrences', 384), ('total_model_source_occurrences', 2144)]:
        r.require(type(summary[key]) is int and summary[key] == n, 'Actual forward accounting differs')
    initial = read(summary['initial_parent_head_parity']['path'], summary['initial_parent_head_parity'])
    final = read(summary['frozen_head_retention']['path'], summary['frozen_head_retention'])
    r.require(initial['source_rows'] == final['source_rows'] == 632 and initial['all_compared_components_bit_equal'] is True
              and final['all_compared_components_bit_equal'] is True and initial['optimizer_updates_before_gate'] == 0,
              'Mandatory actual632 initial/final gates missing')
    for name in PUBLIC_RUNTIME: bind(attempt / name)
    pre = read(attempt / 'pre-admission.json'); terminal_pin = bind(attempt / 'guardian-exit.json'); terminal = read(terminal_pin['path'], terminal_pin)
    r.require(pre['plan'] == plan_pin and pre['review'] == training_review_pin
              and pre['runner'] == bind(F / 'run_temporal_attention_v02.py') and pre['guardian'] == bind(F / 'run_scope_guardian.py'), 'Actual admission source custody differs')
    r.require(terminal['returncode'] == terminal['child_returncode'] == 0 and terminal['artifacts_durable'] is True
              and terminal['resource_reservation_released'] is True, 'Durable released actual guardian success required')
    for path, expected in artifacts.items():
        r.require({k: r.pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Closing full public runtime pin drift')
    for path in all_paths:
        path.chmod(0o444)
        with path.open('rb') as f: os.fsync(f.fileno())
    runtime_path = F / 'runtime-independent-review-v04.json'
    runtime_pin = r.write(runtime_path, dict(schema='temporal-attention-runtime-independent-review/v1', passed=True, findings=[],
        observer=own, independent_source_review=bind(approval_path), artifacts=artifacts, plan=plan_pin, training_review=training_review_pin,
        resource_review=resource_pin, actual_returned_optimizer_updates=32, actual_new_control_optimizer_updates=0,
        actual_model_forwards=1792, actual_inference_source_forwards=1760, actual_training_source_occurrences=384,
        actual_total_source_occurrences=2144, initial_source_rows=632, final_source_rows=632, outputs=74,
        checkpoint_JSON_parses=0, model_or_encoder_calls=0, private_global_body_reads=0, semantic_accuracy=None, default_promotion=False))
    runtime_path.chmod(0o444)
    freeze_path = F / 'temporal-attention-output-freeze-v04.json'
    freeze_pin = r.write(freeze_path, dict(schema='temporal-attention-output-freeze/v1', all_outputs_frozen=True,
        authorizes_authored_eval_scoring=True, evaluation_contract=plan['evaluation_contract'], plan=plan_pin, summary=summary_pin,
        guardian_terminal=terminal_pin, runtime_review=runtime_pin, results=results, actual_returned_optimizer_updates=32,
        actual_new_control_optimizer_updates=0, model_or_encoder_calls=0, checkpoint_JSON_parses=0,
        statutory_reference_scoring_authorized=False, semantic_accuracy=None, default_promotion=False))
    freeze_path.chmod(0o444)
    print(freeze_pin)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args(); main()

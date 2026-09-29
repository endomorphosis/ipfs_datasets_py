"""Small synthetic auditor contract checks; no producer or native execution."""
from pathlib import Path
import copy
import importlib.util
import json
import tempfile

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('audit_helper', BASE / 'audit_native_runs.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
results = {}
workers = [json.loads(path.read_bytes()) for path in (BASE / 'baseline/progress/outputs').glob('*/receipt.json')]
audit = helper.Audit()
for worker in workers:
    helper.audit_refinements(worker['training_report'], 3, audit.check, worker['run_id'])
results['historical_refinement_records_unchanged'] = audit.result()

adapted = []
for worker in workers:
    report = copy.deepcopy(worker['training_report'])
    for epoch in report['epoch_reports']:
        trials = [row for row in epoch['candidate_reports'] if row.get('composed_refinement')]
        for trial in trials:
            trial['evaluation_order'] = 'training_before_validation'
            trial['training_evaluated'] = 'training_after' in trial
            if trial.get('training_reconstruction_delta', 0) <= 0:
                trial.update(holdout_evaluated=False, objective_delta=None,
                             validation_evaluation_skipped_reason='training_screen_rejected')
                for key in ('validation_after', 'cross_entropy_delta'):
                    trial.pop(key, None)
        for seed in epoch['candidate_reports']:
            if 'composed_refinement_reports' in seed:
                seed['composed_refinement_reports'] = trials
    adapted.append(report)
audit = helper.Audit()
for index, report in enumerate(adapted):
    helper.audit_refinements(report, 3, audit.check, str(index), expect_training_first=True)
results['synthetic_training_first_contract'] = audit.result()
mutant = copy.deepcopy(next(report for report in adapted if any(
    row.get('composed_refinement') and row.get('holdout_evaluated') is False
    for row in report['epoch_reports'][0]['candidate_reports'])))
trial = next(row for row in mutant['epoch_reports'][0]['candidate_reports'] if row.get('composed_refinement') and row.get('holdout_evaluated') is False)
trial['objective_delta'] = 0.0
for seed in mutant['epoch_reports'][0]['candidate_reports']:
    if 'composed_refinement_reports' in seed:
        seed['composed_refinement_reports'] = [row for row in mutant['epoch_reports'][0]['candidate_reports'] if row.get('composed_refinement')]
audit = helper.Audit()
helper.audit_refinements(mutant, 3, audit.check, 'mutant', expect_training_first=True)
results['fabricated_validation_delta_rejected'] = any('no_fabricated_skipped_validation' in reason for reason in audit.result()['failures'])

with tempfile.TemporaryDirectory(prefix='search-audit-contract-') as scratch:
    root = Path(scratch)
    autoencoder = 'optimizers/logic_theorem_optimizer/modal_autoencoder.py'
    left = {autoencoder: 'a' * 64, 'logic/sentinel.py': 'c' * 64}
    right = {**left, autoencoder: 'b' * 64}
    for name, value in (('before', left), ('after', right)):
        (root / (name + '.json')).write_text(json.dumps(value))
    approval = {'schema': 'native-optimizer-owned-source-changes/v1', 'allowed_core_roles': ['autoencoder'],
                'before_package_mapping': helper.descriptor(root / 'before.json'),
                'after_package_mapping': helper.descriptor(root / 'after.json'),
                'changes': {autoencoder: {'before': left[autoencoder], 'after': right[autoencoder]}}}
    path = root / 'approval.json'; path.write_text(json.dumps(approval))
    def receipt(mapping):
        return {'producer_manifest': {'sha256': helper.digest(mapping), 'file_count': len(mapping)},
                'core_sources': {'autoencoder': mapping[autoencoder], 'parser': 'd' * 64}}
    audit = helper.Audit()
    helper.audit_owned_source_changes(path, receipt(left), receipt(right), audit)
    results['owned_full_map_delta_accepted'] = audit.result()
    right['logic/sentinel.py'] = 'e' * 64
    (root / 'after.json').write_text(json.dumps(right))
    approval['after_package_mapping'] = helper.descriptor(root / 'after.json')
    approval['changes']['logic/sentinel.py'] = {'before': 'c' * 64, 'after': 'e' * 64}
    path.write_text(json.dumps(approval))
    audit = helper.Audit()
    helper.audit_owned_source_changes(path, receipt(left), receipt(right), audit)
    results['declared_external_drift_still_rejected'] = 'owned_source_delta:exact_owned_allowlist_no_external_drift' in audit.result()['failures']

passed = all(value.get('passed', False) if isinstance(value, dict) else value is True for value in results.values())
output = {'schema': 'native-search-auditor-selfcheck/v1', 'passed': passed, 'results': results,
          'scope': 'Synthetic contract checks and historical receipt reads only; not a new native run, gate admission or performance result.',
          'auditor': helper.descriptor(BASE / 'audit_native_runs.py'), 'admitted': False}
with (BASE / 'audit-helper-selfcheck.json').open('x') as stream:
    json.dump(output, stream, sort_keys=True, indent=2); stream.write('\n')
print(json.dumps(output, sort_keys=True))
raise SystemExit(0 if passed else 1)

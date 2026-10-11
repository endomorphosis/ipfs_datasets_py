"""Declare exact owned evidence copies before the independently reviewed copier runs."""
import hashlib
import json
from pathlib import Path

F = Path(__file__).resolve().parent
N = F.parent / 'legal-native-cache-20261011-01'
P = F.parent / 'legal-open-vocabulary-20261011-01'
ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
RUN = ROOT / 'retained-joint-readout-20261011-01'


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    entries = []

    def add(path, relative, role):
        assert path.is_file() and not path.is_symlink()
        entries.append({'pin': pin(path), 'relative': relative, 'role': role})

    receipts = [
        'canonical-intake.json', 'retained-owner-pins.json', 'raw384-equivalence.json',
        'joint-selector-build.json', 'score-capture-build.json', 'joint-readout-design-review.json',
        'statutory-review-build.json', 'joint-selector-review.json',
        'joint-runner-api-review-v01.json', 'joint-runner-api-review-v02.json', 'joint-runner-api-review-v03.json',
        'score-capture-static-review-v01.json', 'score-capture-static-review-v02.json',
        'statutory-review-independent-v01.json', 'validation.json',
        'joint-inert-tests.xml', 'joint-inert-tests.log', 'capture-inert-tests.xml', 'capture-inert-tests.log',
        'final-inert-tests.xml', 'final-inert-tests.log', 'experiment-plan.json', 'experiment-plan-v02.json',
        'resource-check-invalid-01.stdout', 'resource-check-invalid-01.json', 'resource-compatibility.json',
        'statutory-source-review-packet.json', 'statutory-source-review-template.json',
        'statutory-source-review-validation.json', 'statutory-source-review-packet-build.json',
        'protocol-review-draft-01.json',
        'protocol-review-f7cf97e9361a9b203a2dd90b2a65bfa5d7fdf37b214e450749cda4ae860e5000.json',
        'pre-admission-review-custody.json', 'post-admission-review-custody.json',
        'resource-before-attempt01-pin.json', 'resource-endpoint-preservation.json',
        'guardian-attempt01.log', 'joint-comparison-diagnostics.json', 'analysis-failure-v01.log', 'analysis-v02.log',
        'result-resource-independent-review-v01.json', 'cross-agent-progress-review.json',
        'contribution-design-review-v01.json',
    ]
    for name in receipts:
        add(F / name, 'receipts/' + name, 'owned_receipt')
    helpers = ['run_scope_guardian.py', 'run_inert_tests.py', 'prepare_joint_readout_plan.py',
               'run_joint_readout_comparison.py', 'run_joint_readout_comparison-draft-01.py', 'run_joint_readout_comparison-draft-02.py',
               'build_statutory_review_packet.py', 'analyze_joint_readout.py', 'analyze_joint_readout-draft-01.py',
               'prepare_contribution.py', 'prepare_contribution-draft-01.py', 'prepare_copy_inventory.py',
               'contribution.md', 'contribution-draft-01.md']
    for name in helpers:
        add(F / name, 'helpers/' + name, 'helper')
    attempt_paths = sorted(path for path in RUN.rglob('*') if path.is_file())
    assert len(attempt_paths) == 43
    for path in attempt_paths:
        add(path, 'attempt/' + str(path.relative_to(RUN)), 'owned_attempt')
    for path in sorted((N / 'source-documents').glob('*.txt')):
        add(path, 'source-views/' + path.name, 'raw_source_view')
    for name in ['source-view-provenance.json', 'source-artifact-pins.json', 'source-requests.json']:
        add(N / name, 'source-views/' + name, 'prior_baseline_receipt')
    for path in sorted((ROOT / 'retained-pointer-cache-20261011-03/results').glob('*-1729-*.json')):
        add(path, 'previous-baseline/' + path.name, 'prior_baseline_receipt')
    add(ROOT / 'retained-pointer-cache-20261011-03/results/summary.json', 'previous-baseline/summary.json', 'prior_baseline_receipt')
    add(ROOT / 'arbitrary-native-cache-20261011-02/results/source-production/native384-receipt-001.json',
        'previous-baseline/native384-receipt-001.json', 'prior_baseline_receipt')
    add(P / 'real-law-review-packet.json', 'previous-baseline/real-law-review-packet.json', 'prior_baseline_receipt')
    assert len({entry['relative'] for entry in entries}) == len(entries)
    assert len({entry['pin']['path'] for entry in entries}) == len(entries)
    value = {'schema': 'joint-readout-contribution-inputs/v1', 'entries': entries,
             'full_shared_ledger_included': False, 'raw_weights_included': False,
             'attempt_scope': str(RUN), 'total_input_bytes': sum(entry['pin']['bytes'] for entry in entries)}
    with (F / 'contribution-copy-inputs.json').open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps({'entries': len(entries), 'bytes': value['total_input_bytes']}))


if __name__ == '__main__':
    main()

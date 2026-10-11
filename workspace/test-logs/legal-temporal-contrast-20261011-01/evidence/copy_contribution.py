"""Copy a closed ordinary-file evidence inventory into owned worktrees."""
from pathlib import Path
import hashlib
import json
import os

F = Path(__file__).resolve().parent
ATTEMPT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261011-01')


def pin(path):
    assert path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    names = [
        'intake.json', 'canonical-intake.json', 'main-progress-review-v01.json',
        'resource-compatibility-v01.json', 'resource-ledger-intake-v01.json',
        'temporal-recovery-review-v01.json', 'bootstrap_inert.py', 'run_inert_tests.py',
        'inert-test-observation-v01.json', 'inert-test-observation-v02.json',
        'inert-tests-v01.log', 'inert-tests-v01.xml', 'inert-corpus-tests-v02.log', 'inert-corpus-tests-v02.xml',
        'inert-recipe-tests-v01.log', 'inert-recipe-tests-v01.xml', 'tests/test_temporal_contrast_recipe.py',
        'corpus-draft-v01.py', 'corpus-tests-draft-v01.py', 'runner-draft-v01.py',
        'corpus-independent-review-v01.json', 'corpus-independent-review-v02.json',
        'prepare_temporal_contrast_pilot.py', 'run_temporal_contrast_pilot.py', 'run_scope_guardian.py',
        'authored-temporal-contrast-corpus-v01.json', 'training-export-v01.json', 'inert-ambiguity-audit-v01.json',
        'experiment-plan-v01.json', 'training-protocol-independent-review-v01.json', 'recipe-preflight-v01.json',
        'preparation-execution-v01.log', 'guardian-execution-v01.log', 'storage-admission-diagnosis-v01.json',
        'admission-failure-independent-review-v01.json', 'contribution.md', 'contribution-draft-v01.md',
        'contribution-guide-independent-review-v01.json', 'hf-intake-v01.json', 'hf-before-file-identities-v01.json',
        'prepare_hf_release.py', 'publish_hf_release.py', 'prepare_hf_release-draft-v01.py',
        'publish_hf_release-draft-v01.py', 'prepare_hf_release-draft-v02.py', 'publish_hf_release-draft-v02.py',
        'hf-helper-static-review-v01.json', 'hf-helper-static-review-v02.json', 'copy_contribution.py',
    ]
    entries = {name: pin(F / name) for name in names}
    attempt_names = ['pre-admission.json', 'failure-primary.json', 'child-exit.json',
                     'guardian-exit.json', 'resources-final-failure.json']
    assert {path.name for path in ATTEMPT.iterdir() if path.is_file()} == set(attempt_names)
    for name in attempt_names:
        entries['failed-attempt/' + name] = pin(ATTEMPT / name)
    inventory = dict(schema='temporal-contrast-contribution-inventory/v1', files=entries,
        file_count=len(entries), total_bytes=sum(value['bytes'] for value in entries.values()),
        no_weights=True, guardian_attempt_created=True, numerical_child_started=False,
        actual_model_calls=0, actual_updates=0,
        inventory_scope='owned corrected inputs, tests, protocols, preserved drafts and pre-admission refusal')
    write(F / 'contribution-copy-inputs-v01.json', inventory)
    roots = [F / 'datasets/workspace/test-logs/legal-temporal-contrast-20261011-01/evidence',
             F / 'workspace/artifacts/legal-temporal-contrast-20261011-01/evidence']
    copies = []
    for root in roots:
        assert not root.exists()
        root.mkdir(parents=True)
        for relative, expected in entries.items():
            target = root / relative
            assert target.resolve().is_relative_to(root) and pin(Path(expected['path'])) == expected
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(Path(expected['path']).read_bytes())
            assert {key: pin(target)[key] for key in ('bytes', 'sha256')} == {key: expected[key] for key in ('bytes', 'sha256')}
            assert pin(Path(expected['path'])) == expected
        actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
        assert actual == set(entries) and all(not path.is_symlink() for path in root.rglob('*'))
        copies.append(dict(root=str(root), files=len(actual), byte_exact=True))
    write(F / 'contribution-copy-receipt-v01.json', dict(schema='temporal-contrast-contribution-copies/v1',
        passed=True, findings=[], inventory=pin(F / 'contribution-copy-inputs-v01.json'), copies=copies))
    print(json.dumps(dict(files=len(entries), bytes=inventory['total_bytes'], copies=2)))


if __name__ == '__main__':
    main()

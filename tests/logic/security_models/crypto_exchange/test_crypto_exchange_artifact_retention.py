import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'check_crypto_exchange_artifact_retention.py'
)
BASELINE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'recovery'
    / 'artifact-retention-baseline.json'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'check_crypto_exchange_artifact_retention',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load artifact retention checker')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_retention_baseline_passes_for_current_tree(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'retention-check.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--baseline',
            BASELINE_PATH.as_posix(),
            '--out',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-artifact-retention/v1'
    assert report['task_id'] == 'PORTAL-CXTP-057'
    assert report['overall_status'] == 'pass'
    assert report['proof_acceptance_blocked'] is False
    assert report['security_decision'] == 'ARTIFACT_RETENTION_BASELINE_INTACT'
    assert report['blockers'] == []


def test_retention_baseline_covers_acceptance_artifact_classes() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))
    groups = {group['name']: group for group in baseline['groups']}
    paths_by_group = {
        name: {entry['path'] for entry in group['entries']}
        for name, group in groups.items()
    }

    assert baseline['schema_version'] == 'crypto-exchange-artifact-retention/v1'
    assert baseline['task_id'] == 'PORTAL-CXTP-057'
    assert {
        'taskboard',
        'plans_and_release_policy',
        'source_files',
        'xaman_manifests',
        'model_facts',
        'tests',
        'solver_artifacts',
        'implementation_logs',
        'assurance_packets',
    }.issubset(groups)

    assert (
        'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md'
        in paths_by_group['taskboard']
    )
    assert (
        'docs/security_verification/crypto_exchange_theorem_prover_security_plan.todo.md'
        in paths_by_group['plans_and_release_policy']
    )
    assert (
        'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py'
        in paths_by_group['source_files']
    )
    assert (
        'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
        in paths_by_group['xaman_manifests']
    )
    assert (
        'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json'
        in paths_by_group['model_facts']
    )
    assert (
        'tests/logic/security_models/crypto_exchange/test_crypto_exchange_artifact_retention.py'
        in paths_by_group['tests']
    )
    assert (
        'security_ir_artifacts/assurance-run/smtlib/manifest.json'
        in paths_by_group['solver_artifacts']
    )
    assert (
        'data/crypto_exchange_theorem_prover/state/implementation_logs/portal-cxtp-056-attempt-1.log'
        in paths_by_group['implementation_logs']
    )
    assert 'security_ir_artifacts/assurance-baseline.md' in paths_by_group['assurance_packets']


def test_retention_check_fails_closed_when_required_artifact_disappears(tmp_path: Path) -> None:
    module = _load_script_module()
    required = tmp_path / 'docs' / 'security_verification' / 'taskboard.md'
    required.parent.mkdir(parents=True)
    required.write_text('taskboard evidence\n', encoding='utf-8')

    baseline = {
        'schema_version': module.SCHEMA_VERSION,
        'task_id': module.TASK_ID,
        'groups': [
            {
                'name': 'taskboard',
                'validation': 'sha256',
                'required_count': 1,
                'entries': [
                    {
                        'path': 'docs/security_verification/taskboard.md',
                        'size_bytes': required.stat().st_size,
                        'sha256': module._sha256(required),
                    }
                ],
            }
        ],
    }
    required.unlink()

    report = module.check_retention(baseline, tmp_path)

    assert report['overall_status'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    assert report['security_decision'] == 'BLOCK_PROOF_ACCEPTANCE_ARTIFACT_RETENTION'
    assert report['blockers'] == [
        {
            'code': 'REQUIRED_ARTIFACT_MISSING',
            'group': 'taskboard',
            'count': 1,
            'paths': ['docs/security_verification/taskboard.md'],
        }
    ]


def test_retention_check_fails_closed_when_hashed_artifact_changes(tmp_path: Path) -> None:
    module = _load_script_module()
    artifact = tmp_path / 'security_ir_artifacts' / 'proof-baseline.json'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"status": "reviewed"}\n', encoding='utf-8')
    expected_sha = module._sha256(artifact)
    artifact.write_text('{"status": "mutated"}\n', encoding='utf-8')

    baseline = {
        'schema_version': module.SCHEMA_VERSION,
        'task_id': module.TASK_ID,
        'groups': [
            {
                'name': 'solver_artifacts',
                'validation': 'sha256',
                'required_count': 1,
                'entries': [
                    {
                        'path': 'security_ir_artifacts/proof-baseline.json',
                        'size_bytes': 23,
                        'sha256': expected_sha,
                    }
                ],
            }
        ],
    }

    report = module.check_retention(baseline, tmp_path)

    assert report['overall_status'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    blocker = report['blockers'][0]
    assert blocker['code'] == 'REQUIRED_ARTIFACT_DIGEST_CHANGED'
    assert blocker['group'] == 'solver_artifacts'
    assert blocker['paths'][0]['path'] == 'security_ir_artifacts/proof-baseline.json'

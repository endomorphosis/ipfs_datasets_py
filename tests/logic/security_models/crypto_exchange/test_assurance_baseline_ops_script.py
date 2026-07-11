import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'run_security_ir_assurance_baseline.py'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'run_security_ir_assurance_baseline',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load assurance baseline script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_proof_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                'model_id': 'minimal-btc-exchange',
                'coverage': {
                    'total_claims': 1,
                    'proved': 1,
                    'disproved': 0,
                    'unknown': 0,
                    'not_modeled': 0,
                    'blocking_claims': 1,
                    'blocking_modeled': 1,
                    'blocking_proved': 1,
                },
                'release_gate': {
                    'release_ready': True,
                    'gates': {
                        'blocking': {'total': 1, 'accepted': 1, 'failed': 0, 'attention': 0},
                        'high': {'total': 0, 'accepted': 0, 'failed': 0, 'attention': 0},
                        'medium': {'total': 0, 'accepted': 0, 'failed': 0, 'attention': 0},
                    },
                    'failures': [],
                    'attention': [],
                },
                'assumption_registry': {
                    'release_ready': True,
                    'summary': {
                        'total': 1,
                        'owned': 1,
                        'evidenced': 1,
                        'current': 1,
                        'stale': 0,
                    },
                    'failures': [],
                },
                'reports': [
                    {
                        'claim_id': 'no_unauthorized_withdrawal',
                        'status': 'PROVED',
                        'risk': 'blocking',
                        'assumptions': ['A3'],
                    }
                ],
            }
        ),
        encoding='utf-8',
    )


def _write_minimal_disproof_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                'model_id': 'minimal-btc-exchange',
                'seed': 7,
                'summary': {
                    'scenario_count': 1,
                    'scenario_failures': 0,
                    'total_disproved_claims': 1,
                },
                'scenarios': [],
            }
        ),
        encoding='utf-8',
    )


def test_assurance_baseline_runner_writes_reports_and_summary(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    calls = {}

    def _fake_prove(argv: list[str]) -> int:
        calls['prove'] = argv
        _write_minimal_proof_report(Path(argv[argv.index('--out') + 1]))
        return 0

    def _fake_disproof(argv: list[str]) -> int:
        calls['disproof'] = argv
        _write_minimal_disproof_report(Path(argv[argv.index('--out') + 1]))
        return 0

    monkeypatch.setattr(module, '_z3_version', lambda: '4.test')
    monkeypatch.setattr(module, 'prove_all_main', _fake_prove)
    monkeypatch.setattr(module, 'disproof_main', _fake_disproof)

    assert module.main(['--example', '--out-dir', str(tmp_path), '--fuzz-rounds', '2', '--seed', '11']) == 0

    proof_path = tmp_path / 'proof-baseline.json'
    disproof_path = tmp_path / 'disproof-baseline.json'
    summary_path = tmp_path / 'assurance-baseline.md'
    assert proof_path.exists()
    assert disproof_path.exists()
    assert summary_path.exists()
    summary = summary_path.read_text(encoding='utf-8')
    assert 'Z3 Python bindings: `4.test`' in summary
    assert 'Release ready: `True`' in summary
    assert 'Blocking accepted: `1/1`' in summary
    assert 'Assumption evidence ready: `True`' in summary
    assert 'Owned: `1/1`' in summary
    assert '| `no_unauthorized_withdrawal` | `PROVED` | `blocking` | `A3` |' in summary
    assert '--require-reviewed-evidence' in calls['prove']
    assert '--release-gate' in calls['prove']
    assert '--require-current-assumptions' in calls['prove']
    assert calls['disproof'][calls['disproof'].index('--seed') + 1] == '11'
    assert calls['disproof'][calls['disproof'].index('--fuzz-rounds') + 1] == '2'
    assert calls['disproof'][calls['disproof'].index('--fuzz-exhaustive-max-mutators') + 1] == '2'
    assert calls['disproof'][calls['disproof'].index('--fuzz-max-scenarios') + 1] == '512'
    assert 'Exhaustive mutator combination max: `0`' in summary


def test_assurance_baseline_runner_fails_fast_without_z3(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, '_z3_version', lambda: None)
    monkeypatch.setattr(module, 'prove_all_main', lambda argv: (_ for _ in ()).throw(AssertionError('unexpected proof call')))

    assert module.main(['--example', '--out-dir', str(tmp_path)]) == 2
    assert not (tmp_path / 'proof-baseline.json').exists()


def test_assurance_baseline_runner_stops_when_proof_fails(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, '_z3_version', lambda: '4.test')
    monkeypatch.setattr(module, 'prove_all_main', lambda argv: 1)
    monkeypatch.setattr(module, 'disproof_main', lambda argv: (_ for _ in ()).throw(AssertionError('unexpected disproof call')))

    assert module.main(['--example', '--out-dir', str(tmp_path)]) == 1
    assert not (tmp_path / 'assurance-baseline.md').exists()

from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_tamarin_runtime.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/tamarin-runtime-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_tamarin_runtime.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_tamarin_runtime', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _fake_maude(directory: Path, version: str = '3.5.1') -> Path:
    executable = directory / 'maude'
    executable.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "{version}"\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _fake_tamarin(directory: Path, *, tamarin_version: str = '1.12.0', maude_version: str = '3.5.1') -> Path:
    executable = directory / 'tamarin-prover'
    executable.write_text(
        '#!/bin/sh\n'
        'case " $* " in\n'
        '  *" --version "*)\n'
        "    cat <<'EOF'\n"
        f'tamarin-prover {tamarin_version}, fixture\n'
        f'{maude_version}. OK.\n'
        ' checking installation: OK.\n'
        'Generated from:\n'
        f'Tamarin version {tamarin_version}\n'
        f'Maude version {maude_version}\n'
        'EOF\n'
        '    exit 0\n'
        '    ;;\n'
        '  *" --prove "*)\n'
        '    printf "%s\\n" "runtime_smoke_exists (exists-trace): verified (2 steps)"\n'
        '    exit 0\n'
        '    ;;\n'
        'esac\n'
        'exit 1\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_tamarin_runtime_probe_blocks_when_runtime_is_missing(tmp_path: Path) -> None:
    module = _module()

    report = module.build_tamarin_runtime_report(
        repo_root=ROOT,
        tamarin_executable=tmp_path / 'missing-tamarin-prover',
        maude_executable=tmp_path / 'missing-maude',
    )

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['task_id'] == 'PORTAL-CXTP-141'
    assert report['schema_version'] == 'crypto-exchange-tamarin-runtime-report/v1'
    assert report['overall_status'] == 'blocked_runtime'
    assert report['security_decision'] == 'BLOCK_TAMARIN_MAUDE_RUNTIME_UNAVAILABLE'
    assert 'TAMARIN_EXECUTABLE_MISSING' in codes
    assert 'MAUDE_EXECUTABLE_MISSING' in codes
    assert 'TAMARIN_MINIMAL_THEORY_FAILED' in codes
    assert report['summary']['minimal_theory_passed'] is False
    assert report['artifact_cid'].startswith('sha256:')


def test_tamarin_runtime_probe_accepts_fake_pinned_runtime(tmp_path: Path) -> None:
    module = _module()
    tamarin = _fake_tamarin(tmp_path)
    maude = _fake_maude(tmp_path)

    report = module.build_tamarin_runtime_report(
        repo_root=ROOT,
        tamarin_executable=tamarin,
        maude_executable=maude,
        tamarin_binary=tamarin,
        maude_binary=maude,
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'TAMARIN_MAUDE_RUNTIME_READY'
    assert report['summary']['tamarin_version_pinned'] is True
    assert report['summary']['maude_version'] == '3.5.1'
    assert report['summary']['tamarin_accepts_maude'] is True
    assert report['summary']['minimal_theory_passed'] is True
    assert report['blockers'] == []


def test_tamarin_runtime_rejects_maude_3_2_even_when_fake_tamarin_says_ok(tmp_path: Path) -> None:
    module = _module()
    tamarin = _fake_tamarin(tmp_path, maude_version='3.2')
    maude = _fake_maude(tmp_path, version='3.2')

    report = module.build_tamarin_runtime_report(
        repo_root=ROOT,
        tamarin_executable=tamarin,
        maude_executable=maude,
        tamarin_binary=tamarin,
        maude_binary=maude,
    )

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['overall_status'] == 'blocked_runtime'
    assert 'MAUDE_3_2_NOT_ACCEPTED' in codes
    assert report['summary']['maude_version_rejected'] is True


def test_tamarin_runtime_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    tamarin = _fake_tamarin(tmp_path)
    maude = _fake_maude(tmp_path)
    out = tmp_path / 'tamarin-runtime-report.json'

    exit_code = module.main([
        '--out',
        str(out),
        '--tamarin-executable',
        str(tamarin),
        '--maude-executable',
        str(maude),
        '--tamarin-binary',
        str(tamarin),
        '--maude-binary',
        str(maude),
    ])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-141'
    assert payload['overall_status'] == 'ready'


def test_persisted_tamarin_runtime_report_is_ready() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-141'
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'TAMARIN_MAUDE_RUNTIME_READY'
    assert report['summary']['tamarin_version_pinned'] is True
    assert report['summary']['maude_version'] == '3.5.1'
    assert report['summary']['maude_version_rejected'] is False
    assert report['summary']['tamarin_accepts_maude'] is True
    assert report['summary']['minimal_theory_passed'] is True
    assert report['blockers'] == []
    assert report['executables']['tamarin_prover']['path'] == '/home/barberb/.local/bin/tamarin-prover'
    assert report['executables']['maude']['path'] == '/home/barberb/.local/bin/maude'
    assert report['runtime_artifacts']['maude_archive']['sha256'].startswith('sha256:')
    assert report['minimal_theory']['source_sha256'].startswith('sha256:')
    assert 'runtime_smoke_exists (exists-trace): verified' in report['minimal_theory']['run']['stdout']


def test_tamarin_runtime_documentation_records_scope_and_commands() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-141' in doc
    assert 'Tamarin 1.12.0' in doc
    assert 'Maude 3.5.1' in doc
    assert '/home/barberb/.local/bin/maude' in doc
    assert 'runtime_smoke_exists' in doc
    assert 'Maude 3.2' in doc
    assert 'not accepted as protocol-proof evidence' in doc

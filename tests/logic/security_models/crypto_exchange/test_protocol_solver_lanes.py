from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_protocol_solver_lanes.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/protocol-solver-lane-report.json'
TAMARIN_MODEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy'
PROTOCOL_REPORT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json'
DOC_PATH = ROOT / 'docs/security_verification/protocol_solver_lanes.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_protocol_solver_lanes', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _fake_executable(directory: Path, name: str, output: str = 'protocol solver fixture') -> Path:
    executable = directory / name
    executable.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "{output}"\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_protocol_solver_lane_blocks_when_solvers_are_missing(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, 'find_executable', lambda _name: None)

    report = module.build_protocol_solver_lane_report(repo_root=ROOT)

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['task_id'] == 'PORTAL-CXTP-092'
    assert report['schema_version'] == 'crypto-exchange-protocol-solver-lane-report/v1'
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_PROTOCOL_SOLVER_LANES_UNAVAILABLE'
    assert 'TAMARIN_EXECUTABLE_MISSING' in codes
    assert 'PROVERIF_EXECUTABLE_MISSING' in codes
    assert 'TAMARIN_MODEL_MISSING' not in codes
    assert 'PROVERIF_MODEL_MISSING' not in codes
    assert report['summary']['tamarin_model_present'] is True
    assert report['production_release_blocked_by_protocol_solvers'] is True
    assert report['artifact_cid'].startswith('sha256:')


def test_protocol_solver_lane_can_report_ready_with_fake_solvers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _fake_executable(bin_dir, 'tamarin-prover', 'tamarin fixture')
    _fake_executable(bin_dir, 'proverif', 'proverif fixture')
    monkeypatch.setenv('PATH', bin_dir.as_posix())
    proverif_model = tmp_path / 'xaman_payload_protocol.pv'
    proverif_model.write_text('(* fixture proverif model *)\n', encoding='utf-8')

    report = module.build_protocol_solver_lane_report(
        repo_root=ROOT,
        tamarin_model_path=TAMARIN_MODEL_PATH,
        proverif_model_path=proverif_model,
        protocol_report_path=PROTOCOL_REPORT_PATH,
        run_protocol_checks=True,
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'PROTOCOL_SOLVER_LANES_READY'
    assert report['summary']['tamarin_check_passed'] is True
    assert report['summary']['proverif_check_passed'] is True
    assert report['blockers'] == []


def test_protocol_solver_lane_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'protocol-solver-lane-report.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-092'
    assert payload['overall_status'] in {'ready', 'blocked_optional_lane'}


def test_persisted_protocol_solver_lane_report_is_fail_closed() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-092'
    assert report['overall_status'] in {'ready', 'blocked_optional_lane'}
    if report['overall_status'] == 'ready':
        assert report['security_decision'] == 'PROTOCOL_SOLVER_LANES_READY'
        assert report['summary']['blocker_count'] == 0
        assert report['checks']['tamarin']['status'] == 'passed'
        assert report['checks']['proverif']['status'] == 'passed'
    else:
        assert report['security_decision'] == 'BLOCK_PROTOCOL_SOLVER_LANES_UNAVAILABLE'
        assert report['summary']['blocker_count'] >= 1
        assert report['checks']['tamarin']['status'] == 'not-run'
        assert report['checks']['proverif']['status'] == 'not-run'
        assert report['protocol_report']['overall_status'] == 'blocked_optional_lane'


def test_protocol_solver_lane_documentation_includes_remediation_and_scope() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-092' in doc
    assert 'blocked_optional_lane' in doc
    assert 'tamarin-prover' in doc
    assert 'opam install proverif' in doc
    assert 'not a protocol proof' in doc

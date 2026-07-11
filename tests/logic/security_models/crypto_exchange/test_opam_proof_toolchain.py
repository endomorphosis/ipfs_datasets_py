from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_opam_proof_toolchain.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/opam-proof-toolchain-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_opam_proof_toolchain.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_opam_proof_toolchain', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _wrapper(path: Path, target: Path) -> Path:
    return _make_executable(
        path,
        '#!/bin/sh\n'
        'set -eu\n'
        f'exec "{target.as_posix()}" "$@"\n',
    )


def _fake_toolchain(tmp_path: Path) -> dict[str, Path | str]:
    bin_dir = tmp_path / 'bin'
    target_dir = tmp_path / 'target'
    switch_dir = tmp_path / 'opam-root/xaman-proof'
    switch_bin = switch_dir / 'bin'
    bin_dir.mkdir()
    target_dir.mkdir()
    switch_bin.mkdir(parents=True)

    coqc_target = _make_executable(
        target_dir / 'coqc',
        '#!/bin/sh\n'
        'case " $* " in\n'
        '  *" --version "*) printf "%s\\n" "The Rocq Prover, version 9.1.1"; printf "%s\\n" "compiled with OCaml 4.14.2"; exit 0 ;;\n'
        'esac\n'
        'exit 0\n',
    )
    coqtop_target = _make_executable(
        target_dir / 'coqtop',
        '#!/bin/sh\n'
        'case " $* " in\n'
        '  *" --version "*) printf "%s\\n" "The Rocq Prover, version 9.1.1"; printf "%s\\n" "compiled with OCaml 4.14.2"; exit 0 ;;\n'
        'esac\n'
        'cat >/dev/null\n'
        'printf "%s\\n" "True"\n'
        'exit 0\n',
    )
    proverif_target = _make_executable(
        target_dir / 'proverif',
        '#!/bin/sh\n'
        'case " $* " in\n'
        '  *" -help "*) printf "%s\\n" "Proverif 2.05. Cryptographic protocol verifier"; exit 0 ;;\n'
        'esac\n'
        'printf "%s\\n" "RESULT not attacker(xaman_secret[]) is true."\n'
        'exit 0\n',
    )
    opam = _make_executable(
        bin_dir / 'opam',
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  --version) printf "%s\\n" "2.fixture"; exit 0 ;;\n'
        '  switch) printf "%s\\n" "xaman-proof"; exit 0 ;;\n'
        '  list) cat <<EOF\n'
        '# Packages matching: installed\n'
        '# Name # Version\n'
        'coq 9.1.1\n'
        'coq-core 9.1.1\n'
        'rocq-core 9.1.1\n'
        'ocaml-base-compiler 4.14.2\n'
        'EOF\n'
        '    exit 0 ;;\n'
        '  info) cat <<EOF\n'
        'version      2.05\n'
        'url.src      "https://proverif.inria.fr/proverif2.05.tar.gz"\n'
        'url.checksum "sha256=__SHA__"\n'
        'EOF\n'
        '    exit 0 ;;\n'
        'esac\n'
        'exit 1\n',
    )
    archive = tmp_path / 'proverif2.05.tar.gz'
    archive.write_bytes(b'fixture proverif archive')
    archive_sha = 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()
    opam.write_text(opam.read_text(encoding='utf-8').replace('__SHA__', archive_sha.removeprefix('sha256:')), encoding='utf-8')

    coqc = _wrapper(bin_dir / 'coqc', coqc_target)
    coqtop = _wrapper(bin_dir / 'coqtop', coqtop_target)
    proverif = _wrapper(bin_dir / 'proverif', proverif_target)
    return {
        'opam_root': tmp_path / 'opam-root',
        'opam': opam,
        'coqc': coqc,
        'coqtop': coqtop,
        'proverif': proverif,
        'coqc_target': coqc_target,
        'coqtop_target': coqtop_target,
        'proverif_target': proverif_target,
        'archive': archive,
        'archive_sha': archive_sha,
    }


def test_opam_proof_toolchain_blocks_when_required_paths_are_missing(tmp_path: Path) -> None:
    module = _module()

    report = module.build_opam_proof_toolchain_report(
        repo_root=ROOT,
        opam_root=tmp_path / 'missing-opam-root',
        opam_executable=tmp_path / 'missing-opam',
        coqc_wrapper=tmp_path / 'missing-coqc',
        coqtop_wrapper=tmp_path / 'missing-coqtop',
        proverif_wrapper=tmp_path / 'missing-proverif',
        proverif_archive=tmp_path / 'missing-proverif.tar.gz',
    )

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['task_id'] == 'PORTAL-CXTP-142'
    assert report['schema_version'] == 'crypto-exchange-opam-proof-toolchain-report/v1'
    assert report['overall_status'] == 'blocked_toolchain'
    assert report['security_decision'] == 'BLOCK_OPAM_PROOF_TOOLCHAIN_INCOMPLETE'
    assert 'OPAM_EXECUTABLE_MISSING' in codes
    assert 'OPAM_SWITCH_MISSING' in codes
    assert 'COQC_WRAPPER_MISSING' in codes
    assert 'PROVERIF_MINIMAL_CHECK_FAILED' in codes
    assert report['testnet_protocol_or_independent_kernel_coverage_blocked'] is True
    assert report['artifact_cid'].startswith('sha256:')


def test_opam_proof_toolchain_accepts_fake_pinned_wrappers(tmp_path: Path) -> None:
    module = _module()
    fixture = _fake_toolchain(tmp_path)

    report = module.build_opam_proof_toolchain_report(
        repo_root=ROOT,
        opam_root=fixture['opam_root'],
        opam_executable=fixture['opam'],
        coqc_wrapper=fixture['coqc'],
        coqtop_wrapper=fixture['coqtop'],
        proverif_wrapper=fixture['proverif'],
        proverif_archive=fixture['archive'],
        expected_coqc_target=fixture['coqc_target'],
        expected_coqtop_target=fixture['coqtop_target'],
        expected_proverif_target=fixture['proverif_target'],
        expected_proverif_archive_sha256=fixture['archive_sha'],
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'OPAM_PROOF_TOOLCHAIN_READY'
    assert report['summary']['opam_switch_present'] is True
    assert report['summary']['coq_version_pinned'] is True
    assert report['summary']['proverif_version_pinned'] is True
    assert report['summary']['coqc_minimal_check_passed'] is True
    assert report['summary']['coqtop_minimal_check_passed'] is True
    assert report['summary']['proverif_minimal_check_passed'] is True
    assert report['blockers'] == []


def test_opam_proof_toolchain_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    fixture = _fake_toolchain(tmp_path)
    out = tmp_path / 'opam-proof-toolchain-report.json'

    exit_code = module.main([
        '--out',
        str(out),
        '--opam-root',
        str(fixture['opam_root']),
        '--opam-executable',
        str(fixture['opam']),
        '--coqc-wrapper',
        str(fixture['coqc']),
        '--coqtop-wrapper',
        str(fixture['coqtop']),
        '--proverif-wrapper',
        str(fixture['proverif']),
        '--proverif-archive',
        str(fixture['archive']),
    ])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-142'
    assert payload['overall_status'] in {'ready', 'blocked_toolchain'}


def test_persisted_opam_proof_toolchain_report_is_ready() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-142'
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'OPAM_PROOF_TOOLCHAIN_READY'
    assert report['summary']['opam_switch_present'] is True
    assert report['summary']['coq_version_pinned'] is True
    assert report['summary']['ocaml_version_pinned'] is True
    assert report['summary']['proverif_version_pinned'] is True
    assert report['summary']['coqc_minimal_check_passed'] is True
    assert report['summary']['coqtop_minimal_check_passed'] is True
    assert report['summary']['proverif_minimal_check_passed'] is True
    assert report['blockers'] == []
    assert report['executables']['coqc']['wrapper_path'] == '/home/barberb/.local/bin/coqc'
    assert report['executables']['coqtop']['wrapper_path'] == '/home/barberb/.local/bin/coqtop'
    assert report['executables']['proverif']['wrapper_path'] == '/home/barberb/.local/bin/proverif'
    assert report['minimal_checks']['proverif']['expected_result'] in report['minimal_checks']['proverif']['run']['stdout']


def test_opam_proof_toolchain_documentation_records_scope_and_refresh_command() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-142' in doc
    assert 'OPAM_PROOF_TOOLCHAIN_READY' in doc
    assert 'xaman-proof' in doc
    assert '/home/barberb/.local/bin/coqc' in doc
    assert '/home/barberb/.local/bin/coqtop' in doc
    assert '/home/barberb/.local/bin/proverif' in doc
    assert 'RESULT not attacker(xaman_secret[]) is true' in doc
    assert 'not a proof of the Xaman Testnet protocol model' in doc

#!/usr/bin/env python3
"""Attest the pinned OPAM Coq/Rocq and ProVerif proof toolchain."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-opam-proof-toolchain-report/v1'
TASK_ID = 'PORTAL-CXTP-142'
DEFAULT_OUT = Path('security_ir_artifacts/environment/opam-proof-toolchain-report.json')
SOLVER_ROOT = Path.home() / '.local/share/xaman-proof-solvers'
LOCAL_BIN = Path.home() / '.local/bin'
DEFAULT_OPAM_ROOT = SOLVER_ROOT / 'opam-root'
DEFAULT_SWITCH = 'xaman-proof'
DEFAULT_OPAM_BINARY = LOCAL_BIN / 'opam'
DEFAULT_COQC_WRAPPER = LOCAL_BIN / 'coqc'
DEFAULT_COQTOP_WRAPPER = LOCAL_BIN / 'coqtop'
DEFAULT_PROVERIF_WRAPPER = LOCAL_BIN / 'proverif'
DEFAULT_PROVERIF_ARCHIVE = SOLVER_ROOT / 'downloads/proverif2.05.tar.gz'
EXPECTED_COQ_VERSION = '9.1.1'
EXPECTED_OCAML_VERSION = '4.14.2'
EXPECTED_PROVERIF_VERSION = '2.05'
EXPECTED_PROVERIF_ARCHIVE_SHA256 = 'sha256:4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4'

MINIMAL_COQ_SOURCE = '''Theorem xaman_opam_coq_smoke : True.
Proof. exact I. Qed.
'''
MINIMAL_COQTOP_INPUT = 'Check True.\n'
MINIMAL_PROVERIF_SOURCE = '''free c: channel.
free xaman_secret: bitstring [private].
query attacker(xaman_secret).
process 0
'''


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_bytes(payload: bytes) -> str:
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def _sha256_text(payload: str) -> str:
    return _sha256_bytes(payload.encode('utf-8'))


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return _sha256_bytes(canonical)


def _path_or_none(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    candidate = Path(value).expanduser()
    return candidate if candidate.is_file() else None


def _resolve_executable(explicit: Path | str | None, name: str) -> Path | None:
    if explicit is not None:
        return _path_or_none(explicit)
    resolved = shutil.which(name)
    return Path(resolved) if resolved else None


def _run(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env) if env is not None else None,
            input=input_text,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'status': 'timeout',
            'returncode': None,
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'command': list(command),
        }
    except OSError as exc:
        return {
            'status': 'unavailable',
            'returncode': None,
            'stdout': '',
            'stderr': str(exc),
            'command': list(command),
        }
    return {
        'status': 'passed' if completed.returncode == 0 else 'failed',
        'returncode': completed.returncode,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
        'command': list(command),
    }


def _opam_env(opam_root: Path, extra_path: Sequence[Path]) -> dict[str, str]:
    env = os.environ.copy()
    env['OPAMROOT'] = opam_root.as_posix()
    path_prefix = os.pathsep.join(path.as_posix() for path in extra_path if path)
    env['PATH'] = path_prefix + (os.pathsep + env.get('PATH', '') if path_prefix else env.get('PATH', ''))
    return env


def _first_line(run: Mapping[str, Any]) -> str:
    output = (run.get('stdout') or run.get('stderr') or '').strip().splitlines()
    return output[0] if output else ''


def _coq_version(executable: Path | None) -> str:
    if executable is None:
        return ''
    run = _run([executable.as_posix(), '--version'], timeout=10)
    return ((run.get('stdout') or '') + (run.get('stderr') or '')).strip()


def _proverif_version(executable: Path | None) -> str:
    if executable is None:
        return ''
    for args in (['-help'], ['--help'], []):
        run = _run([executable.as_posix(), *args], timeout=10)
        text = (run.get('stdout') or '') + (run.get('stderr') or '')
        match = re.search(r'Proverif\s+([0-9]+(?:\.[0-9]+)*)', text)
        if match:
            return match.group(1)
    return ''


def _parse_coq_release(version_output: str) -> str | None:
    match = re.search(r'version\s+([0-9]+(?:\.[0-9]+)*)', version_output, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _parse_ocaml_release(version_output: str) -> str | None:
    match = re.search(r'OCaml\s+([0-9]+(?:\.[0-9]+)*)', version_output, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _wrapper_target(wrapper: Path | None) -> Path | None:
    if wrapper is None or not wrapper.is_file():
        return None
    try:
        text = wrapper.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return wrapper
    match = re.search(r'exec\s+"?\$HOME/([^"\s]+)"?', text)
    if match:
        return Path.home() / match.group(1)
    match = re.search(r'exec\s+"?(/[^"\s]+)"?', text)
    if match:
        return Path(match.group(1))
    return wrapper


def _executable_record(name: str, wrapper: Path | None, expected_target: Path | None, root: Path) -> dict[str, Any]:
    target = _wrapper_target(wrapper)
    return {
        'name': name,
        'wrapper_path': wrapper.as_posix() if wrapper else None,
        'wrapper_relative_path': _relative(wrapper, root) if wrapper else None,
        'wrapper_exists': wrapper.is_file() if wrapper else False,
        'wrapper_sha256': _sha256(wrapper),
        'target_path': target.as_posix() if target else None,
        'target_exists': target.is_file() if target else False,
        'target_sha256': _sha256(target),
        'expected_target_path': expected_target.as_posix() if expected_target else None,
        'matches_expected_target': target.resolve() == expected_target.resolve() if target and expected_target else False,
    }


def _artifact_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        'path': path.as_posix(),
        'relative_path': _relative(path, root),
        'exists': path.is_file(),
        'sha256': _sha256(path),
    }


def _opam_command(opam: Path | None, args: Sequence[str], env: Mapping[str, str]) -> dict[str, Any]:
    if opam is None:
        return {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'opam executable is missing',
            'command': ['opam', *args],
        }
    return _run([opam.as_posix(), *args], env=env, timeout=30)


def _installed_packages(opam: Path | None, switch: str, env: Mapping[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
    run = _opam_command(opam, ['list', f'--switch={switch}', '--installed', '--columns=name,version'], env)
    packages: dict[str, str] = {}
    if run['status'] == 'passed':
        for line in (run.get('stdout') or '').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                packages[parts[0]] = parts[1]
    return packages, run


def _opam_info_proverif(opam: Path | None, env: Mapping[str, str]) -> dict[str, Any]:
    run = _opam_command(opam, ['info', f'proverif.{EXPECTED_PROVERIF_VERSION}'], env)
    output = (run.get('stdout') or '') + (run.get('stderr') or '')
    checksum_match = re.search(r'sha256=([0-9a-f]{64})', output)
    source_match = re.search(r'url\.src\s+"([^"]+)"', output)
    return {
        'run': run,
        'version': EXPECTED_PROVERIF_VERSION if f'version      {EXPECTED_PROVERIF_VERSION}' in output else None,
        'url_src': source_match.group(1) if source_match else None,
        'url_sha256': 'sha256:' + checksum_match.group(1) if checksum_match else None,
    }


def _run_coqc_smoke(coqc: Path | None) -> dict[str, Any]:
    if coqc is None:
        return {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'coqc wrapper is missing',
            'command': ['coqc', 'xaman_opam_coq_smoke.v'],
        }
    with tempfile.TemporaryDirectory(prefix='xaman-opam-coq-') as tmp:
        source = Path(tmp) / 'xaman_opam_coq_smoke.v'
        source.write_text(MINIMAL_COQ_SOURCE, encoding='utf-8')
        return _run([coqc.as_posix(), source.as_posix()], timeout=30)


def _run_coqtop_smoke(coqtop: Path | None) -> dict[str, Any]:
    if coqtop is None:
        return {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'coqtop wrapper is missing',
            'command': ['coqtop', '-quiet'],
        }
    return _run([coqtop.as_posix(), '-quiet'], input_text=MINIMAL_COQTOP_INPUT, timeout=30)


def _run_proverif_smoke(proverif: Path | None) -> dict[str, Any]:
    if proverif is None:
        return {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'proverif wrapper is missing',
            'command': ['proverif', 'xaman_opam_proverif_smoke.pv'],
        }
    with tempfile.TemporaryDirectory(prefix='xaman-opam-proverif-') as tmp:
        source = Path(tmp) / 'xaman_opam_proverif_smoke.pv'
        source.write_text(MINIMAL_PROVERIF_SOURCE, encoding='utf-8')
        return _run([proverif.as_posix(), source.as_posix()], timeout=30)


def build_opam_proof_toolchain_report(
    *,
    repo_root: Path | str | None = None,
    opam_root: Path | str = DEFAULT_OPAM_ROOT,
    switch: str = DEFAULT_SWITCH,
    opam_executable: Path | str | None = None,
    coqc_wrapper: Path | str | None = None,
    coqtop_wrapper: Path | str | None = None,
    proverif_wrapper: Path | str | None = None,
    proverif_archive: Path | str = DEFAULT_PROVERIF_ARCHIVE,
    expected_coqc_target: Path | str | None = None,
    expected_coqtop_target: Path | str | None = None,
    expected_proverif_target: Path | str | None = None,
    expected_proverif_archive_sha256: str = EXPECTED_PROVERIF_ARCHIVE_SHA256,
    run_smoke: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    opam_root_path = Path(opam_root).expanduser()
    proverif_archive_path = Path(proverif_archive).expanduser()
    opam = _resolve_executable(opam_executable if opam_executable is not None else DEFAULT_OPAM_BINARY, 'opam')
    coqc = _resolve_executable(coqc_wrapper if coqc_wrapper is not None else DEFAULT_COQC_WRAPPER, 'coqc')
    coqtop = _resolve_executable(coqtop_wrapper if coqtop_wrapper is not None else DEFAULT_COQTOP_WRAPPER, 'coqtop')
    proverif = _resolve_executable(
        proverif_wrapper if proverif_wrapper is not None else DEFAULT_PROVERIF_WRAPPER,
        'proverif',
    )
    switch_prefix = opam_root_path / switch
    switch_bin = switch_prefix / 'bin'
    env = _opam_env(opam_root_path, [LOCAL_BIN, switch_bin])

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if opam is None:
        blockers.append({'code': 'OPAM_EXECUTABLE_MISSING', 'message': 'opam executable is not available'})
    if not opam_root_path.is_dir():
        blockers.append({'code': 'OPAM_ROOT_MISSING', 'message': f'{opam_root_path.as_posix()} is missing'})
    if not switch_prefix.is_dir():
        blockers.append({'code': 'OPAM_SWITCH_MISSING', 'message': f'OPAM switch {switch!r} is missing'})
    for name, executable in (('coqc', coqc), ('coqtop', coqtop), ('proverif', proverif)):
        if executable is None:
            blockers.append({'code': f'{name.upper()}_WRAPPER_MISSING', 'message': f'{name} wrapper is missing'})

    opam_version = _opam_command(opam, ['--version'], env)
    switch_list = _opam_command(opam, ['switch', 'list', '--short'], env)
    switch_present = switch in (switch_list.get('stdout') or '').split()
    if switch_list['status'] != 'passed':
        blockers.append({'code': 'OPAM_SWITCH_LIST_FAILED', 'message': switch_list.get('stderr') or 'opam switch list failed'})
    elif not switch_present:
        blockers.append({'code': 'OPAM_SWITCH_NOT_LISTED', 'message': f'OPAM switch {switch!r} is not listed'})

    packages, package_run = _installed_packages(opam, switch, env)
    if package_run['status'] != 'passed':
        blockers.append({'code': 'OPAM_PACKAGE_LIST_FAILED', 'message': package_run.get('stderr') or 'opam list failed'})

    coqc_version = _coq_version(coqc)
    coqtop_version = _coq_version(coqtop)
    proverif_version = _proverif_version(proverif)
    parsed_coq = _parse_coq_release(coqc_version)
    parsed_coqtop = _parse_coq_release(coqtop_version)
    parsed_ocaml = _parse_ocaml_release(coqc_version)
    if parsed_coq != EXPECTED_COQ_VERSION:
        blockers.append({
            'code': 'COQC_VERSION_NOT_PINNED',
            'message': f'Expected coqc/Rocq {EXPECTED_COQ_VERSION}, observed {parsed_coq!r}',
        })
    if parsed_coqtop != EXPECTED_COQ_VERSION:
        blockers.append({
            'code': 'COQTOP_VERSION_NOT_PINNED',
            'message': f'Expected coqtop/Rocq {EXPECTED_COQ_VERSION}, observed {parsed_coqtop!r}',
        })
    if parsed_ocaml != EXPECTED_OCAML_VERSION:
        blockers.append({
            'code': 'OCAML_VERSION_NOT_PINNED',
            'message': f'Expected OCaml {EXPECTED_OCAML_VERSION}, observed {parsed_ocaml!r}',
        })
    if proverif_version != EXPECTED_PROVERIF_VERSION:
        blockers.append({
            'code': 'PROVERIF_VERSION_NOT_PINNED',
            'message': f'Expected ProVerif {EXPECTED_PROVERIF_VERSION}, observed {proverif_version!r}',
        })

    required_packages = {
        'coq': EXPECTED_COQ_VERSION,
        'coq-core': EXPECTED_COQ_VERSION,
        'rocq-core': EXPECTED_COQ_VERSION,
        'ocaml-base-compiler': EXPECTED_OCAML_VERSION,
    }
    for package, expected_version in required_packages.items():
        if packages.get(package) != expected_version:
            blockers.append({
                'code': f'OPAM_PACKAGE_{package.upper().replace("-", "_")}_NOT_PINNED',
                'message': f'Expected OPAM package {package}={expected_version}, observed {packages.get(package)!r}',
            })

    opam_proverif_info = _opam_info_proverif(opam, env)
    archive_sha = _sha256(proverif_archive_path)
    if archive_sha != expected_proverif_archive_sha256:
        blockers.append({
            'code': 'PROVERIF_ARCHIVE_DIGEST_MISMATCH',
            'message': f'Expected ProVerif archive {expected_proverif_archive_sha256}, observed {archive_sha!r}',
        })
    if opam_proverif_info['url_sha256'] != expected_proverif_archive_sha256:
        warnings.append({
            'code': 'PROVERIF_OPAM_INDEX_DIGEST_UNAVAILABLE',
            'message': 'Could not confirm the ProVerif 2.05 archive checksum from the OPAM index',
        })
    if packages.get('proverif') != EXPECTED_PROVERIF_VERSION:
        warnings.append({
            'code': 'PROVERIF_NOT_INSTALLED_AS_OPAM_PACKAGE',
            'message': 'The ProVerif wrapper targets a pinned upstream 2.05 source build whose archive digest matches the OPAM index; the package is not installed in the switch package database.',
        })

    expected_targets = {
        'coqc': Path(expected_coqc_target).expanduser() if expected_coqc_target else switch_bin / 'coqc',
        'coqtop': Path(expected_coqtop_target).expanduser() if expected_coqtop_target else switch_bin / 'coqtop',
        'proverif': (
            Path(expected_proverif_target).expanduser()
            if expected_proverif_target
            else SOLVER_ROOT / 'src/proverif2.05/proverif'
        ),
    }
    executable_records = {
        'coqc': _executable_record('coqc', coqc, expected_targets['coqc'], root),
        'coqtop': _executable_record('coqtop', coqtop, expected_targets['coqtop'], root),
        'proverif': _executable_record('proverif', proverif, expected_targets['proverif'], root),
    }
    for name, record in executable_records.items():
        if not record['target_exists']:
            blockers.append({'code': f'{name.upper()}_TARGET_MISSING', 'message': f"{name} wrapper target is missing"})
        if not record['matches_expected_target']:
            blockers.append({
                'code': f'{name.upper()}_WRAPPER_TARGET_UNEXPECTED',
                'message': f"{name} wrapper target {record['target_path']!r} does not match {record['expected_target_path']!r}",
            })

    coqc_smoke = _run_coqc_smoke(coqc) if run_smoke else {
        'status': 'not-run',
        'returncode': None,
        'stdout': '',
        'stderr': 'Coq smoke run disabled by caller',
        'command': [coqc.as_posix() if coqc else 'coqc', 'xaman_opam_coq_smoke.v'],
    }
    coqtop_smoke = _run_coqtop_smoke(coqtop) if run_smoke else {
        'status': 'not-run',
        'returncode': None,
        'stdout': '',
        'stderr': 'Coqtop smoke run disabled by caller',
        'command': [coqtop.as_posix() if coqtop else 'coqtop', '-quiet'],
    }
    proverif_smoke = _run_proverif_smoke(proverif) if run_smoke else {
        'status': 'not-run',
        'returncode': None,
        'stdout': '',
        'stderr': 'ProVerif smoke run disabled by caller',
        'command': [proverif.as_posix() if proverif else 'proverif', 'xaman_opam_proverif_smoke.pv'],
    }
    coqc_verified = coqc_smoke['status'] == 'passed'
    coqtop_verified = coqtop_smoke['status'] == 'passed' and 'True' in (
        (coqtop_smoke.get('stdout') or '') + (coqtop_smoke.get('stderr') or '')
    )
    proverif_output = (proverif_smoke.get('stdout') or '') + (proverif_smoke.get('stderr') or '')
    proverif_verified = (
        proverif_smoke['status'] == 'passed'
        and 'RESULT not attacker(xaman_secret[]) is true' in proverif_output
    )
    if not coqc_verified:
        blockers.append({'code': 'COQC_MINIMAL_CHECK_FAILED', 'message': coqc_smoke.get('stderr') or 'coqc smoke check failed'})
    if not coqtop_verified:
        blockers.append({'code': 'COQTOP_MINIMAL_CHECK_FAILED', 'message': coqtop_smoke.get('stderr') or 'coqtop smoke check failed'})
    if not proverif_verified:
        blockers.append({'code': 'PROVERIF_MINIMAL_CHECK_FAILED', 'message': proverif_smoke.get('stderr') or 'ProVerif smoke check failed'})

    ready = not blockers
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'depends_on': ['PORTAL-CXTP-092'],
        'generated_at': _utc_now(),
        'pinned_versions': {
            'coq_compat_package': EXPECTED_COQ_VERSION,
            'rocq_core': EXPECTED_COQ_VERSION,
            'ocaml_base_compiler': EXPECTED_OCAML_VERSION,
            'proverif': EXPECTED_PROVERIF_VERSION,
            'proverif_archive_sha256': expected_proverif_archive_sha256,
        },
        'opam': {
            'root': opam_root_path.as_posix(),
            'root_exists': opam_root_path.is_dir(),
            'switch': switch,
            'switch_prefix': switch_prefix.as_posix(),
            'switch_prefix_exists': switch_prefix.is_dir(),
            'switch_bin': switch_bin.as_posix(),
            'switch_listed': switch_present,
            'executable': opam.as_posix() if opam else None,
            'executable_sha256': _sha256(opam),
            'version': _first_line(opam_version),
            'version_check': opam_version,
            'switch_list_check': switch_list,
            'package_list_check': package_run,
            'installed_packages': packages,
        },
        'executables': executable_records,
        'tool_versions': {
            'coqc': coqc_version,
            'coqtop': coqtop_version,
            'proverif': proverif_version,
            'parsed': {
                'coqc_release': parsed_coq,
                'coqtop_release': parsed_coqtop,
                'ocaml_release_from_coqc': parsed_ocaml,
                'proverif_release': proverif_version or None,
            },
        },
        'proverif_source': {
            'archive': _artifact_record(proverif_archive_path, root),
            'opam_index': opam_proverif_info,
            'provenance': 'upstream_source_archive_matching_opam_checksum',
            'installed_as_opam_package': packages.get('proverif') == EXPECTED_PROVERIF_VERSION,
        },
        'minimal_checks': {
            'coqc': {
                'name': 'xaman_opam_coq_smoke',
                'source': MINIMAL_COQ_SOURCE,
                'source_sha256': _sha256_text(MINIMAL_COQ_SOURCE),
                'run': coqc_smoke,
                'verified': coqc_verified,
            },
            'coqtop': {
                'name': 'xaman_opam_coqtop_smoke',
                'input': MINIMAL_COQTOP_INPUT,
                'input_sha256': _sha256_text(MINIMAL_COQTOP_INPUT),
                'run': coqtop_smoke,
                'verified': coqtop_verified,
            },
            'proverif': {
                'name': 'xaman_opam_proverif_smoke',
                'source': MINIMAL_PROVERIF_SOURCE,
                'source_sha256': _sha256_text(MINIMAL_PROVERIF_SOURCE),
                'expected_result': 'RESULT not attacker(xaman_secret[]) is true',
                'run': proverif_smoke,
                'verified': proverif_verified,
            },
        },
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'opam_switch_present': switch_present and switch_prefix.is_dir(),
            'coqc_wrapper_ready': executable_records['coqc']['wrapper_exists'] and executable_records['coqc']['target_exists'],
            'coqtop_wrapper_ready': executable_records['coqtop']['wrapper_exists'] and executable_records['coqtop']['target_exists'],
            'proverif_wrapper_ready': executable_records['proverif']['wrapper_exists'] and executable_records['proverif']['target_exists'],
            'coq_version_pinned': parsed_coq == EXPECTED_COQ_VERSION and parsed_coqtop == EXPECTED_COQ_VERSION,
            'ocaml_version_pinned': parsed_ocaml == EXPECTED_OCAML_VERSION,
            'proverif_version_pinned': proverif_version == EXPECTED_PROVERIF_VERSION,
            'proverif_archive_matches_opam_index': archive_sha == expected_proverif_archive_sha256,
            'coqc_minimal_check_passed': coqc_verified,
            'coqtop_minimal_check_passed': coqtop_verified,
            'proverif_minimal_check_passed': proverif_verified,
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'overall_status': 'ready' if ready else 'blocked_toolchain',
        'security_decision': 'OPAM_PROOF_TOOLCHAIN_READY' if ready else 'BLOCK_OPAM_PROOF_TOOLCHAIN_INCOMPLETE',
        'testnet_protocol_or_independent_kernel_coverage_blocked': not ready,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--opam-root', type=Path, default=DEFAULT_OPAM_ROOT)
    parser.add_argument('--switch', default=DEFAULT_SWITCH)
    parser.add_argument('--opam-executable', type=Path)
    parser.add_argument('--coqc-wrapper', type=Path)
    parser.add_argument('--coqtop-wrapper', type=Path)
    parser.add_argument('--proverif-wrapper', type=Path)
    parser.add_argument('--proverif-archive', type=Path, default=DEFAULT_PROVERIF_ARCHIVE)
    parser.add_argument('--skip-smoke', action='store_true')
    args = parser.parse_args(argv)

    report = build_opam_proof_toolchain_report(
        opam_root=args.opam_root,
        switch=args.switch,
        opam_executable=args.opam_executable,
        coqc_wrapper=args.coqc_wrapper,
        coqtop_wrapper=args.coqtop_wrapper,
        proverif_wrapper=args.proverif_wrapper,
        proverif_archive=args.proverif_archive,
        run_smoke=not args.skip_smoke,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Redacted iOS/XCTest host preflight for Xaman native-vault fault injection.

This check only confirms a prepared Darwin/Xcode host and required source
artifacts for XCTest execution. It does not build Xaman, run tests, start
simulators, capture traces, or authorize any runtime evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import platform
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-168'
SCHEMA_VERSION = 'xaman-native-vault-ios-host-preflight/v1'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'

WORKSPACE_PATH = Path('ios/Xaman.xcworkspace/contents.xcworkspacedata')
VAULT_TEST_PATH = Path('ios/XamanTests/VaultMangerTest.m')
VAULT_MANAGER_PATH = Path('ios/Xaman/Libs/Security/Vault/VaultManager.m')

SIMULATOR_LINE_RE = re.compile(r'^\s*[^\s].+\([0-9a-fA-F-]{36}\)\s+\([^)]*\)\s*$')


class IOSHostPreflightError(ValueError):
    """Raised when the supplied iOS host cannot support the test lane."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _cid_without(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _run_command(
    command: Sequence[str],
    *,
    label: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=dict(environment) if environment is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IOSHostPreflightError(f'{label} could not be executed') from exc
    output = (completed.stdout + '\n' + completed.stderr).strip()
    if completed.returncode != 0 or not output:
        raise IOSHostPreflightError(f'{label} did not return usable output')
    return output


def _run_command_raw(command: Sequence[str], *, label: str) -> str:
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IOSHostPreflightError(f'{label} could not be executed') from exc
    output = (completed.stdout + '\n' + completed.stderr).strip()
    if completed.returncode != 0 or not output:
        raise IOSHostPreflightError(f'{label} did not return usable output')
    return output


def _blocked_preflight_payload(
    *,
    platform_name: str,
    blockers: Iterable[str],
    source_root: Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    blocked_sources = [
        {
            'source_root': str(source_root.resolve()),
            'clean_checkout': source_root.is_dir() and not any(source_root.joinpath('.git').iterdir())
            if (source_root / '.git').is_dir()
            else False,
        }
    ]
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc,
        'host_paths_redacted': True,
        'platform': platform_name,
        'toolchain': {
            'xcodebuild': {'executable': False, 'version': None, 'sha256': None},
            'xcrun': {'executable': False, 'version': None, 'sha256': None},
            'simctl': {'executable': False, 'version': None, 'sha256': None},
        },
        'simulator': {
            'available_ios_simulator_count': 0,
            'ios_runtime_available': False,
            'simctl_supported': False,
            'simctl_resolves_on_host': False,
        },
        'source': {
            'source_commit': None,
            'clean_checkout': None,
            'files': {},
            'source_root_check': blocked_sources,
        },
        'capability': {
            'ios_xctest_host_prepared': False,
            'simulator_started_by_this_check': False,
            'xaman_build_or_test_started_by_this_check': False,
            'runtime_capture_recorded': False,
            'independent_review_required_before_capture': True,
            'android_host_verified_by_this_check': False,
        },
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'remaining_blockers': [
            'iOS preflight requires Darwin host',
            *list(blockers),
        ],
        'security_decision': 'IOS_NATIVE_VAULT_HOST_PREPARED_BLOCKED_NON_DARWIN',
    }
    report['artifact_cid'] = _cid_without(report)
    return report


def _contains(path: Path, marker: str) -> bool:
    return marker in path.read_text(encoding='utf-8', errors='ignore')


def _count_available_simulators(raw: str) -> int:
    return sum(1 for line in raw.splitlines() if SIMULATOR_LINE_RE.match(line.strip()))


def _ios_runtime_available(raw: str) -> bool:
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith('iOS') and 'unavailable' not in stripped.lower():
            return True
    return False


def _require_source_markers(source_root: Path) -> dict[str, bool]:
    workspace = source_root / WORKSPACE_PATH
    tests = source_root / VAULT_TEST_PATH
    manager = source_root / VAULT_MANAGER_PATH
    checks = {
        'workspace_has_vault_tests_target': (
            workspace.is_file() and _contains(workspace, 'XamanTests')
        ),
        'vault_test_contains_rekey': (
            tests.is_file() and _contains(tests, 'testVaultReKey')
        ),
        'vault_test_contains_recovery': (
            tests.is_file() and _contains(tests, 'testVaultRecovery')
        ),
        'vault_manager_batch_hook_present': (
            manager.is_file() and _contains(manager, 'reKeyBatchVaults')
        ),
    }
    for key, valid in checks.items():
        if not valid:
            raise IOSHostPreflightError(f'{key.replace("_", " ")} marker check failed')
    return checks


def _build_source_file_hashes(source_root: Path) -> dict[str, str]:
    return {
        'workspace_sha256': _sha256_file(source_root / WORKSPACE_PATH),
        'vault_test_sha256': _sha256_file(source_root / VAULT_TEST_PATH),
        'vault_manager_sha256': _sha256_file(source_root / VAULT_MANAGER_PATH),
    }


def build_ios_host_preflight(
    *,
    xcodebuild: Path,
    xcrun: Path,
    simctl: Path,
    source_root: Path,
    tool_versions: Mapping[str, str],
    available_ios_simulator_count: int,
    ios_runtime_available: bool,
    source_commit: str,
    clean_checkout: bool,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Build a redacted iOS host preflight report for native-vault runtime work."""

    if source_commit != PINNED_XAMAN_COMMIT:
        raise IOSHostPreflightError('source commit does not match pinned Xaman corpus')
    if not source_root.is_dir():
        raise IOSHostPreflightError('source_root is not a directory')
    if not clean_checkout:
        raise IOSHostPreflightError('source checkout is not clean')
    if available_ios_simulator_count < 1:
        raise IOSHostPreflightError('no available iOS simulators were observed')
    if not ios_runtime_available:
        raise IOSHostPreflightError('no iOS simulator runtime was observed')

    for name, path in {'xcodebuild': xcodebuild, 'xcrun': xcrun, 'simctl': simctl}.items():
        if not path.is_file() or not path.stat().st_mode & 0o100:
            raise IOSHostPreflightError(f'{name} is missing or not executable')

    for name in ('xcodebuild', 'xcrun', 'simctl'):
        version = tool_versions.get(name)
        if not isinstance(version, str) or not version.strip():
            raise IOSHostPreflightError('tool version observations are invalid')

    marker_checks = _require_source_markers(source_root)
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc,
        'host_paths_redacted': True,
        'toolchain': {
            'xcodebuild': {
                'version': tool_versions['xcodebuild'],
                'sha256': _sha256_file(xcodebuild),
                'executable': True,
            },
            'xcrun': {
                'version': tool_versions['xcrun'],
                'sha256': _sha256_file(xcrun),
                'executable': True,
            },
            'simctl': {
                'version': tool_versions['simctl'],
                'sha256': _sha256_file(simctl),
                'executable': True,
            },
        },
        'simulator': {
            'available_ios_simulator_count': available_ios_simulator_count,
            'ios_runtime_available': ios_runtime_available,
            'simctl_supported': True,
            'simctl_resolves_on_host': True,
        },
        'source': {
            'source_commit': source_commit,
            'clean_checkout': clean_checkout,
            'files': {
                **marker_checks,
                **_build_source_file_hashes(source_root),
            },
        },
        'capability': {
            'ios_xctest_host_prepared': True,
            'simulator_started_by_this_check': False,
            'xaman_build_or_test_started_by_this_check': False,
            'runtime_capture_recorded': False,
            'independent_review_required_before_capture': True,
            'android_host_verified_by_this_check': False,
        },
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'remaining_blockers': [
            'PORTAL-CXTP-156 independent review decision',
            'separate reviewed Android verifier-only host for fault injection',
            'runtime injection evidence for all twelve cases',
        ],
        'security_decision': 'IOS_NATIVE_VAULT_HOST_PREPARED_PENDING_REVIEW_AND_RUNTIME',
    }
    report['artifact_cid'] = _cid_without(report)
    return report


def probe_ios_host(
    *,
    xcodebuild: Path,
    xcrun: Path,
    source_root: Path,
    emit_blocked_artifact: bool = False,
) -> dict[str, Any]:
    """Probe explicit host and source inputs for an iOS XCTest host preflight."""

    if platform.system() != 'Darwin':
        if not emit_blocked_artifact:
            raise IOSHostPreflightError('iOS preflight requires Darwin host')
        return _blocked_preflight_payload(
            platform_name=platform.system(),
            blockers=['Non-Darwin host detected'],
            source_root=source_root,
            generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        )
    if not source_root.is_dir():
        raise IOSHostPreflightError('source_root is not a directory')

    xcodebuild_version = _run_command([str(xcodebuild), '-version'], label='xcodebuild')
    xcrun_version = _run_command([str(xcrun), '--version'], label='xcrun')
    simctl_path_output = _run_command([str(xcrun), '--find', 'simctl'], label='xcrun --find simctl')
    simctl_path = Path(simctl_path_output.splitlines()[0].strip())

    if not xcodebuild.is_file() or not xcodebuild.stat().st_mode & 0o100:
        raise IOSHostPreflightError('xcodebuild is not executable')
    if not xcrun.is_file() or not xcrun.stat().st_mode & 0o100:
        raise IOSHostPreflightError('xcrun is not executable')
    if not simctl_path.is_file() or not simctl_path.stat().st_mode & 0o100:
        raise IOSHostPreflightError('simctl is unavailable from xcrun')

    available_device_listing = _run_command_raw(
        [str(xcrun), 'simctl', 'list', 'devices', 'available'],
        label='simctl available devices',
    )
    runtimes = _run_command_raw([str(xcrun), 'simctl', 'list', 'runtimes'], label='simctl runtimes')
    available_ios_simulator_count = _count_available_simulators(available_device_listing)
    ios_runtime_available = _ios_runtime_available(runtimes)

    git_commit = _run_command(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], label='git commit')
    git_status = _run_command_raw(['git', '-C', str(source_root), 'status', '--porcelain'], label='git status')
    clean_checkout = not bool(git_status.strip())

    return build_ios_host_preflight(
        xcodebuild=xcodebuild,
        xcrun=xcrun,
        simctl=simctl_path,
        source_root=source_root,
        tool_versions={
            'xcodebuild': xcodebuild_version,
            'xcrun': xcrun_version,
            'simctl': xcrun_version,
        },
        available_ios_simulator_count=available_ios_simulator_count,
        ios_runtime_available=ios_runtime_available,
        source_commit=git_commit,
        clean_checkout=clean_checkout,
        generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    )

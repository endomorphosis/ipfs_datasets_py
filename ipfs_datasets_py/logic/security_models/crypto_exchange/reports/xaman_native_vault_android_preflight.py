"""Redacted Android host preflight for Xaman native-vault fault injection.

This check establishes only that an explicitly supplied Android SDK and API-34
AVD are usable inputs for a future verifier-only test.  It never starts an
emulator, builds Xaman, captures a wallet trace, or authorizes runtime work.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-166'
SCHEMA_VERSION = 'xaman-native-vault-android-host-preflight/v1'
AVD_NAME = 'xaman-testnet-api34'
REQUIRED_AVD_CONFIG = {
    'abi.type': 'x86_64',
    'hw.cpu.arch': 'x86_64',
    'tag.id': 'google_apis',
    'PlayStore.enabled': 'no',
}
REQUIRED_AVD_TARGET = 'android-34'


class AndroidHostPreflightError(ValueError):
    """Raised when the supplied Android host cannot support the test lane."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _cid_without(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _run_version(command: list[str], *, label: str, environment: Mapping[str, str] | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=dict(environment) if environment is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AndroidHostPreflightError(f'{label} could not be executed') from exc
    output = (completed.stdout + '\n' + completed.stderr).strip()
    if completed.returncode != 0 or not output:
        raise AndroidHostPreflightError(f'{label} did not return version output')
    return output.splitlines()[0].strip()


def build_android_host_preflight(
    *,
    sdkmanager: Path,
    adb: Path,
    emulator: Path,
    avd_config: Path,
    avd_ini: Path,
    avd_name: str,
    tool_versions: Mapping[str, str],
    emulator_avds: list[str],
    generated_at_utc: str,
) -> dict[str, Any]:
    """Build a content-addressed, path-redacted Android-host preparation report."""

    if avd_name != AVD_NAME:
        raise AndroidHostPreflightError(f'AVD must be {AVD_NAME}')
    for name, path in {'sdkmanager': sdkmanager, 'adb': adb, 'emulator': emulator, 'avd_config': avd_config, 'avd_ini': avd_ini}.items():
        if not path.is_file():
            raise AndroidHostPreflightError(f'{name} is missing')
    if avd_name not in emulator_avds:
        raise AndroidHostPreflightError('configured AVD is not listed by the emulator')
    config = _read_properties(avd_config)
    avd_definition = _read_properties(avd_ini)
    for key, expected in REQUIRED_AVD_CONFIG.items():
        if config.get(key) != expected:
            raise AndroidHostPreflightError(f'AVD config {key} must be {expected}')
    if avd_definition.get('target') != REQUIRED_AVD_TARGET:
        raise AndroidHostPreflightError(f'AVD target must be {REQUIRED_AVD_TARGET}')
    for name, value in tool_versions.items():
        if name not in {'sdkmanager', 'adb', 'emulator'} or not isinstance(value, str) or not value:
            raise AndroidHostPreflightError('tool version observations are invalid')

    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc,
        'host_paths_redacted': True,
        'toolchain': {
            name: {
                'version': tool_versions[name],
                'sha256': _sha256_file(path),
                'executable': True,
            }
            for name, path in {'sdkmanager': sdkmanager, 'adb': adb, 'emulator': emulator}.items()
        },
        'avd': {
            'name': avd_name,
            'target': avd_definition['target'],
            'abi': config['abi.type'],
            'cpu_arch': config['hw.cpu.arch'],
            'tag': config['tag.id'],
            'play_store_enabled': False,
            'config_sha256': _sha256_file(avd_config),
            'listed_by_emulator': True,
        },
        'capability': {
            'android_fault_injection_host_prepared': True,
            'emulator_started_by_this_check': False,
            'xaman_build_or_test_started_by_this_check': False,
            'runtime_capture_recorded': False,
            'independent_review_required_before_capture': True,
            'ios_xctest_host_verified_by_this_check': False,
        },
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'remaining_blockers': [
            'PORTAL-CXTP-156 independent review decision',
            'separate macOS/Xcode iOS XCTest host',
            'reviewed verifier-only Android and iOS fault-injection execution',
        ],
        'security_decision': 'ANDROID_NATIVE_VAULT_HOST_PREPARED_PENDING_REVIEW_AND_IOS',
    }
    report['artifact_cid'] = _cid_without(report)
    return report


def probe_android_host(
    *,
    android_sdk: Path,
    avd_home: Path,
    avd_name: str = AVD_NAME,
    java_home: Path | None = None,
) -> dict[str, Any]:
    """Probe explicit Android tool paths without launching an AVD or app."""

    sdkmanager = android_sdk / 'cmdline-tools/latest/bin/sdkmanager'
    adb = android_sdk / 'platform-tools/adb'
    emulator = android_sdk / 'emulator/emulator'
    for path in (sdkmanager, adb, emulator):
        if not path.is_file() or not path.stat().st_mode & 0o100:
            raise AndroidHostPreflightError('required Android SDK executable is unavailable')
    avd_config = avd_home / f'{avd_name}.avd/config.ini'
    avd_ini = avd_home / f'{avd_name}.ini'
    environment = os.environ.copy()
    if java_home is not None:
        if not (java_home / 'bin/java').is_file():
            raise AndroidHostPreflightError('java_home does not contain bin/java')
        environment['JAVA_HOME'] = str(java_home)
    tool_versions = {
        'sdkmanager': _run_version([str(sdkmanager), '--version'], label='sdkmanager', environment=environment),
        'adb': _run_version([str(adb), 'version'], label='adb', environment=environment),
        'emulator': _run_version([str(emulator), '-version'], label='emulator', environment=environment),
    }
    listed = _run_version([str(emulator), '-list-avds'], label='emulator AVD listing', environment=environment).splitlines()
    return build_android_host_preflight(
        sdkmanager=sdkmanager,
        adb=adb,
        emulator=emulator,
        avd_config=avd_config,
        avd_ini=avd_ini,
        avd_name=avd_name,
        tool_versions=tool_versions,
        emulator_avds=listed,
        generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    )

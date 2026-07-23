"""Tests for the Android native-vault host preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_android_preflight import (
    AndroidHostPreflightError,
    build_android_host_preflight,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/runtime/native-vault-android-host-preflight.json'


def _write(path: Path, payload: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')
    if executable:
        path.chmod(0o755)


def _build(tmp_path: Path, *, tag: str = 'google_apis') -> dict[str, object]:
    sdkmanager = tmp_path / 'sdk/cmdline-tools/latest/bin/sdkmanager'
    adb = tmp_path / 'sdk/platform-tools/adb'
    emulator = tmp_path / 'sdk/emulator/emulator'
    for executable in (sdkmanager, adb, emulator):
        _write(executable, '#!/bin/sh\n', executable=True)
    avd_home = tmp_path / 'avd'
    config = avd_home / 'xaman-testnet-api34.avd/config.ini'
    ini = avd_home / 'xaman-testnet-api34.ini'
    _write(config, f'abi.type=x86_64\nhw.cpu.arch=x86_64\ntag.id={tag}\nPlayStore.enabled=no\n')
    _write(ini, 'target=android-34\n')
    return build_android_host_preflight(
        sdkmanager=sdkmanager,
        adb=adb,
        emulator=emulator,
        avd_config=config,
        avd_ini=ini,
        avd_name='xaman-testnet-api34',
        tool_versions={'sdkmanager': '19.0', 'adb': 'Android Debug Bridge 37', 'emulator': 'Android emulator 36'},
        emulator_avds=['xaman-testnet-api34'],
        generated_at_utc='2026-07-18T20:00:00Z',
    )


def test_preflight_prepares_android_without_starting_runtime(tmp_path: Path) -> None:
    report = _build(tmp_path)

    assert report['capability']['android_fault_injection_host_prepared'] is True
    assert report['capability']['emulator_started_by_this_check'] is False
    assert report['capability']['xaman_build_or_test_started_by_this_check'] is False
    assert report['capability']['runtime_capture_recorded'] is False
    assert report['scope']['vendor_release_equivalent'] is False
    assert str(tmp_path) not in json.dumps(report)


def test_preflight_rejects_wrong_avd_configuration(tmp_path: Path) -> None:
    with pytest.raises(AndroidHostPreflightError, match='tag.id'):
        _build(tmp_path, tag='google_apis_playstore')


def test_checked_in_preflight_is_content_addressed_and_preserves_boundaries() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    body = {key: value for key, value in report.items() if key != 'artifact_cid'}

    assert report['artifact_cid'] == calculate_artifact_cid(body)
    assert report['host_paths_redacted'] is True
    assert report['capability']['runtime_capture_recorded'] is False
    assert report['capability']['ios_xctest_host_verified_by_this_check'] is False

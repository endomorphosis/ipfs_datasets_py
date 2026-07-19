"""Tests for the iOS native-vault host preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_ios_preflight import (
    IOSHostPreflightError,
    PINNED_XAMAN_COMMIT,
    build_ios_host_preflight,
    probe_ios_host,
)


def _write(path: Path, payload: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')
    if executable:
        path.chmod(0o755)


def _build(
    tmp_path: Path,
    *,
    simulator_count: int = 1,
    ios_runtime_available: bool = True,
    clean_checkout: bool = True,
    source_commit: str = PINNED_XAMAN_COMMIT,
) -> dict[str, object]:
    xcodebuild = tmp_path / 'xcodebuild'
    xcrun = tmp_path / 'xcrun'
    simctl = tmp_path / 'simctl'
    for executable in (xcodebuild, xcrun, simctl):
        _write(executable, '#!/bin/sh\n', executable=True)

    source_root = tmp_path / 'xaman'
    workspace = source_root / 'ios/Xaman.xcworkspace/contents.xcworkspacedata'
    test_file = source_root / 'ios/XamanTests/VaultMangerTest.m'
    manager_file = source_root / 'ios/Xaman/Libs/Security/Vault/VaultManager.m'
    _write(workspace, '<string>XamanTests</string>\n')
    _write(test_file, 'testVaultReKey\\ntestVaultRecovery\\n')
    _write(manager_file, 'reKeyBatchVaults\\n')

    return build_ios_host_preflight(
        xcodebuild=xcodebuild,
        xcrun=xcrun,
        simctl=simctl,
        source_root=source_root,
        tool_versions={
            'xcodebuild': 'Xcode 15.4',
            'xcrun': 'xcrun 0.0',
            'simctl': 'simctl 0.0',
        },
        available_ios_simulator_count=simulator_count,
        ios_runtime_available=ios_runtime_available,
        source_commit=source_commit,
        clean_checkout=clean_checkout,
        generated_at_utc='2026-07-18T20:00:00Z',
    )


def test_preflight_prepares_ios_without_starting_runtime(tmp_path: Path) -> None:
    report = _build(tmp_path)

    assert report['capability']['ios_xctest_host_prepared'] is True
    assert report['capability']['simulator_started_by_this_check'] is False
    assert report['capability']['xaman_build_or_test_started_by_this_check'] is False
    assert report['capability']['runtime_capture_recorded'] is False
    assert report['scope']['vendor_release_equivalent'] is False
    assert str(tmp_path) not in json.dumps(report)


def test_preflight_rejects_cleaning_requirements(tmp_path: Path) -> None:
    with pytest.raises(IOSHostPreflightError, match='no available iOS simulators'):
        _build(tmp_path, simulator_count=0)


def test_preflight_rejects_wrong_commit(tmp_path: Path) -> None:
    with pytest.raises(IOSHostPreflightError, match='source commit does not match pinned'):
        _build(tmp_path, source_commit='bad')


def test_preflight_rejects_dirty_checkout(tmp_path: Path) -> None:
    with pytest.raises(IOSHostPreflightError, match='source checkout is not clean'):
        _build(tmp_path, clean_checkout=False)


def test_preflight_rejects_missing_marker(tmp_path: Path) -> None:
    source_root = tmp_path / 'xaman'
    test_file = source_root / 'ios/XamanTests/VaultMangerTest.m'
    _write(test_file, 'no marker\\n', executable=False)
    workspace = source_root / 'ios/Xaman.xcworkspace/contents.xcworkspacedata'
    manager_file = source_root / 'ios/Xaman/Libs/Security/Vault/VaultManager.m'
    _write(workspace, '<string>XamanTests</string>\\n')
    _write(manager_file, 'reKeyBatchVaults\\n')
    xcodebuild = tmp_path / 'xcodebuild'
    xcrun = tmp_path / 'xcrun'
    simctl = tmp_path / 'simctl'
    for executable in (xcodebuild, xcrun, simctl):
        _write(executable, '#!/bin/sh\\n', executable=True)
    with pytest.raises(IOSHostPreflightError, match='marker check failed'):
        build_ios_host_preflight(
            xcodebuild=xcodebuild,
            xcrun=xcrun,
            simctl=simctl,
            source_root=source_root,
            tool_versions={
                'xcodebuild': 'Xcode 15.4',
                'xcrun': 'xcrun 0.0',
                'simctl': 'simctl 0.0',
            },
            available_ios_simulator_count=1,
            ios_runtime_available=True,
            source_commit=PINNED_XAMAN_COMMIT,
            clean_checkout=True,
            generated_at_utc='2026-07-18T20:00:00Z',
        )


def test_build_is_content_addressed_when_recomputed(tmp_path: Path) -> None:
    report = _build(tmp_path)
    rebuilt = build_ios_host_preflight(
        xcodebuild=tmp_path / 'xcodebuild',
        xcrun=tmp_path / 'xcrun',
        simctl=tmp_path / 'simctl',
        source_root=tmp_path / 'xaman',
        tool_versions={
            'xcodebuild': 'Xcode 15.4',
            'xcrun': 'xcrun 0.0',
            'simctl': 'simctl 0.0',
        },
        available_ios_simulator_count=1,
        ios_runtime_available=True,
        source_commit=PINNED_XAMAN_COMMIT,
        clean_checkout=True,
        generated_at_utc='2026-07-18T20:00:00Z',
    )
    assert report['artifact_cid'] == rebuilt['artifact_cid']
    assert report['host_paths_redacted'] is True
    assert report['capability']['runtime_capture_recorded'] is False
    assert report['capability']['android_host_verified_by_this_check'] is False
    assert str(tmp_path) not in json.dumps(report)


def test_probe_reports_darwin_requirement(tmp_path: Path) -> None:
    source_root = tmp_path / 'xaman'
    source_root.mkdir(parents=True)
    source_root.joinpath('.git').mkdir()

    xcodebuild = tmp_path / 'xcodebuild'
    xcrun = tmp_path / 'xcrun'
    _write(xcodebuild, '#!/bin/sh\n', executable=True)
    _write(xcrun, '#!/bin/sh\n', executable=True)

    with pytest.raises(IOSHostPreflightError, match='iOS preflight requires Darwin host'):
        probe_ios_host(xcodebuild=xcodebuild, xcrun=xcrun, source_root=source_root)


def test_probe_can_emit_blocked_artifact_on_non_darwin(tmp_path: Path) -> None:
    source_root = tmp_path / 'xaman'
    source_root.mkdir(parents=True)
    source_root.joinpath('.git').mkdir()

    xcodebuild = tmp_path / 'xcodebuild'
    xcrun = tmp_path / 'xcrun'
    _write(xcodebuild, '#!/bin/sh\n', executable=True)
    _write(xcrun, '#!/bin/sh\n', executable=True)

    report = probe_ios_host(
        xcodebuild=xcodebuild,
        xcrun=xcrun,
        source_root=source_root,
        emit_blocked_artifact=True,
    )

    assert report['security_decision'] == 'IOS_NATIVE_VAULT_HOST_PREPARED_BLOCKED_NON_DARWIN'
    assert report['capability']['ios_xctest_host_prepared'] is False
    assert report['scope']['vendor_release_equivalent'] is False
    assert report['platform'] == 'Linux'

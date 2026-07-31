"""Runtime dependency regressions for the TLC/Apalache installer."""

from __future__ import annotations

from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.installers import state_model


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_java(path: Path, version: str, *, runtime_exit: int = 0) -> Path:
    return _write_executable(
        path,
        (
            'if [ "${1:-}" = "-version" ]; then\n'
            f'  echo \'openjdk version "{version}"\' >&2\n'
            "  exit 0\n"
            "fi\n"
            'echo "TLC runtime probe" >&2\n'
            f"exit {runtime_exit}"
        ),
    )


def test_java_major_version_handles_legacy_and_modern_banners() -> None:
    assert state_model.java_major_version('java version "1.8.0_482"') == 8
    assert state_model.java_major_version('openjdk version "11.0.27"') == 11
    assert state_model.java_major_version('openjdk version "17.0.12"') == 17
    assert state_model.java_major_version("not a Java banner") is None


def test_explicit_java_override_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java8 = _fake_java(tmp_path / "java8" / "java", "1.8.0_482")
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    monkeypatch.setenv("PATH", str(java17.parent))

    probe = state_model.probe_java_runtime(
        java_executable=java8,
        minimum_major=state_model.APALACHE_MIN_JAVA_MAJOR,
    )

    assert probe.executable == str(java8.resolve())
    assert probe.source == "argument"
    assert probe.major == 8
    assert probe.usable is False
    assert probe.reason_code == "java_version_unsupported"


def test_invalid_java_environment_override_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    monkeypatch.setenv("PATH", str(java17.parent))
    monkeypatch.setenv(
        state_model.JAVA_EXECUTABLE_ENV,
        str(tmp_path / "missing-java"),
    )

    probe = state_model.probe_java_runtime(
        minimum_major=state_model.TLC_MIN_JAVA_MAJOR,
    )

    assert probe.executable is None
    assert probe.source == "environment"
    assert probe.reason_code == "java_override_invalid"


def test_apalache_probe_rejects_nonzero_version_banner(
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    apalache = _write_executable(
        tmp_path / "apalache-mc",
        'echo "Apalache 0.58.3" >&2\nexit 1',
    )

    probe = state_model.probe_apalache_runtime(
        str(apalache),
        java_executable=java17,
    )

    assert probe.usable is False
    assert probe.returncode == 1
    assert probe.reason_code == "runtime_probe_nonzero_exit"


def test_tlc_version_probe_rejects_nonzero_banner(
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    tlc = _write_executable(
        tmp_path / "tlc",
        'echo "TLC 1.8.0" >&2\nexit 1',
    )

    banner = state_model.read_tlc_version_banner(
        str(tlc),
        jar_path=tmp_path / "missing.jar",
        java_executable=java17,
    )

    assert banner is None


def test_ensure_apalache_blocks_java_below_certified_minimum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java8 = _fake_java(tmp_path / "java8" / "java", "1.8.0_482")
    monkeypatch.setattr(
        state_model,
        "download_artifact",
        lambda *args, **kwargs: pytest.fail("download must not be attempted"),
    )

    receipt = state_model.ensure_apalache(
        yes=True,
        strict=False,
        force=True,
        install_root=tmp_path / "install",
        java_executable=java8,
        test_mode=True,
    )

    assert receipt.status == "blocked"
    assert receipt.phase == "java_support"
    assert "java_version_unsupported" in receipt.reason_codes
    assert receipt.bindings["java_major"] == 8
    assert receipt.bindings["minimum_java_major"] == 17
    assert receipt.install_attempted is False


def test_tlc_post_install_probe_fails_before_launcher_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(
        tmp_path / "java17" / "java",
        "17.0.12",
        runtime_exit=1,
    )
    install_root = tmp_path / "install"

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"not-a-real-jar")
        return True, "a" * 64

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )

    receipt = state_model.ensure_tlc(
        yes=True,
        strict=False,
        force=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert receipt.status == "failed"
    assert receipt.phase == "runtime_validation"
    assert "post_install_usability_failed" in receipt.reason_codes
    assert receipt.installed is False
    assert not (install_root / "bin" / state_model.TLC_EXECUTABLE).exists()


def test_apalache_post_install_probe_fails_before_launcher_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"not-a-real-archive")
        return True, "b" * 64

    def fake_extract(archive: Path, destination: Path) -> None:
        _write_executable(
            destination / "apalache-0.58.3" / "bin" / "apalache-mc",
            'echo "Apalache 0.58.3" >&2\nexit 1',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "_safe_extract_tar", fake_extract)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )

    receipt = state_model.ensure_apalache(
        yes=True,
        strict=False,
        force=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert receipt.status == "failed"
    assert receipt.phase == "runtime_validation"
    assert "post_install_usability_failed" in receipt.reason_codes
    assert receipt.installed is False
    assert not (install_root / "bin" / state_model.APALACHE_EXECUTABLE).exists()


def test_successful_apalache_install_binds_selected_java(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"not-a-real-archive")
        return True, "c" * 64

    def fake_extract(archive: Path, destination: Path) -> None:
        _write_executable(
            destination / "apalache-0.58.3" / "bin" / "apalache-mc",
            'echo "Apalache 0.58.3"',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "_safe_extract_tar", fake_extract)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )

    receipt = state_model.ensure_apalache(
        yes=True,
        strict=False,
        force=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    launcher = install_root / "bin" / state_model.APALACHE_EXECUTABLE
    assert receipt.status == "installed"
    assert receipt.installed is True
    assert launcher.is_file()
    body = launcher.read_text(encoding="utf-8")
    assert f"export PATH='{java17.parent.resolve()}':" in body
    assert receipt.bindings["post_install_runtime_probe"]["usable"] is True

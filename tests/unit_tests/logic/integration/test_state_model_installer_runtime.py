"""Runtime dependency regressions for the TLC/Apalache installer."""

from __future__ import annotations

from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.installers import state_model

TLC_HELP_OUTPUT = """\
NAME
    TLC - provides model checking and simulation of TLA+ specifications - Version 2026.07.31
SYNOPSIS
    TLC [options] SPEC
DESCRIPTION
    The model checker (TLC) checks or simulates TLA+ specifications.
"""


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_java(
    path: Path,
    version: str,
    *,
    runtime_exit: int = 0,
    runtime_output: str = "TLC runtime probe",
) -> Path:
    return _write_executable(
        path,
        (
            'if [ "${1:-}" = "-version" ]; then\n'
            f'  echo \'openjdk version "{version}"\' >&2\n'
            "  exit 0\n"
            "fi\n"
            "cat <<'TLC_OUTPUT'\n"
            f"{runtime_output.rstrip()}\n"
            "TLC_OUTPUT\n"
            f"exit {runtime_exit}"
        ),
    )


def test_java_major_version_handles_legacy_and_modern_banners() -> None:
    assert state_model.java_major_version('java version "1.8.0_482"') == 8
    assert state_model.java_major_version('openjdk version "11.0.27"') == 11
    assert state_model.java_major_version('openjdk version "17.0.12"') == 17
    assert state_model.java_major_version("not a Java banner") is None


def test_java_major_version_ignores_injected_dotted_marker() -> None:
    banner = (
        "Picked up JAVA_TOOL_OPTIONS: -Dreview.marker=17.0\n"
        'openjdk version "1.8.0_482"\n'
        "OpenJDK Runtime Environment (build 1.8.0_482)"
    )

    assert state_model.java_major_version(banner) == 8


@pytest.mark.parametrize(
    "variable",
    state_model.JAVA_OPTION_ENV_VARS,
)
def test_java_probe_sanitizes_option_environment(
    variable: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java = _write_executable(
        tmp_path / "java",
        (
            f'if [ "${{{variable}+set}}" = set ]; then exit 91; fi\n'
            'echo \'openjdk version "1.8.0_482"\' >&2'
        ),
    )
    monkeypatch.setenv(variable, "-Dreview.marker=17.0")

    probe = state_model.probe_java_runtime(
        java_executable=java,
        minimum_major=17,
    )

    assert probe.major == 8
    assert probe.usable is False
    assert probe.reason_code == "java_version_unsupported"


def test_bare_java_resolves_only_through_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_java = _fake_java(tmp_path / "java", "21.0.9")
    monkeypatch.chdir(tmp_path)

    assert state_model.which_executable("java", path_env="/missing") is None
    assert state_model.which_executable("./java", path_env="/missing") == str(
        local_java.resolve()
    )


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


def test_tlc_probe_accepts_real_help_semantics_with_exit_one(
    tmp_path: Path,
) -> None:
    java17 = _fake_java(
        tmp_path / "java17" / "java",
        "17.0.12",
        runtime_exit=1,
        runtime_output=TLC_HELP_OUTPUT,
    )
    jar = tmp_path / state_model.TLC_JAR_NAME
    jar.write_bytes(b"fixture-identity-is-verified-separately")

    probe = state_model.probe_tlc_runtime(
        jar_path=jar,
        java_executable=java17,
    )

    assert probe.usable is True
    assert probe.returncode == 1
    assert "TLC - provides model checking" in probe.output


def test_blank_tlc_lock_digest_fails_closed() -> None:
    lock = {
        "managed_pin_versions": {"tlc": state_model.TLC_VERSION},
        "tools": [
            {
                "tool_id": "tlc",
                "pins": [
                    {
                        "tool_id": "tlc",
                        "version": state_model.TLC_VERSION,
                        "platform": "any",
                        "artifact_url": "https://example.invalid/tla2tools.jar",
                        "sha256": "",
                        "is_checksummed": False,
                    }
                ],
            }
        ],
    }

    with pytest.raises(state_model.StateModelInstallerError, match="digest"):
        state_model.select_strict_pin("tlc", lock=lock)


def test_dry_run_executes_no_host_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "executed"
    executable = _write_executable(
        tmp_path / "java",
        f"touch '{marker}'\nexit 99",
    )
    monkeypatch.setattr(
        state_model,
        "which_executable",
        lambda *args, **kwargs: pytest.fail("dry-run resolved an executable"),
    )
    monkeypatch.setattr(
        state_model,
        "probe_java_runtime",
        lambda *args, **kwargs: pytest.fail("dry-run probed the JVM"),
    )

    receipt = state_model.ensure_state_model_portfolio(
        yes=True,
        strict=True,
        dry_run=True,
        install_root=tmp_path / "install",
        java_executable=executable,
    )

    assert receipt["tlc"]["phase"] == "dry_run"
    assert receipt["apalache"]["phase"] == "dry_run"
    assert receipt["java_runtime"]["reason_code"] == "dry_run_not_probed"
    assert not marker.exists()


@pytest.mark.parametrize("tool", ["tlc", "apalache"])
def test_live_ensure_cannot_disable_java_validation(
    tool: str,
    tmp_path: Path,
) -> None:
    ensure = (
        state_model.ensure_tlc
        if tool == "tlc"
        else state_model.ensure_apalache
    )

    receipt = ensure(
        yes=True,
        strict=False,
        force=True,
        install_root=tmp_path / "install",
        require_java=False,
    )

    assert receipt.status == "failed"
    assert "java_validation_opt_out_forbidden" in receipt.reason_codes
    assert receipt.install_attempted is False


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
    final_jar = (
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    )
    final_jar.parent.mkdir(parents=True)
    final_jar.write_bytes(b"previous-valid-install")
    old_launcher = _write_executable(
        install_root / "bin" / state_model.TLC_EXECUTABLE,
        'echo "previous launcher"',
    )
    previous_launcher = old_launcher.read_bytes()

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"not-a-real-jar")
        return True, state_model.TLC_SHA256

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
    assert final_jar.read_bytes() == b"previous-valid-install"
    assert old_launcher.read_bytes() == previous_launcher


def test_atomic_file_publication_restores_all_prior_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "final" / "first"
    second = tmp_path / "final" / "second"
    staged_first = tmp_path / "staged" / "first"
    staged_second = tmp_path / "staged" / "second"
    for path, value in (
        (first, b"old-first"),
        (second, b"old-second"),
        (staged_first, b"new-first"),
        (staged_second, b"new-second"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    original_replace = Path.replace

    def fail_second(source: Path, target: Path):
        if source == staged_second:
            raise OSError("injected publication failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second)

    with pytest.raises(OSError, match="injected"):
        state_model._commit_staged_files(
            ((staged_first, first), (staged_second, second)),
            backup_dir=tmp_path / "backups",
        )

    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"


def test_successful_tlc_install_accepts_real_help_exit_and_binds_java(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(
        tmp_path / "java17" / "java",
        "17.0.12",
        runtime_exit=1,
        runtime_output=TLC_HELP_OUTPUT,
    )
    install_root = tmp_path / "install"

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"reviewed-tlc-fixture")
        return True, state_model.TLC_SHA256

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

    launcher = install_root / "bin" / state_model.TLC_EXECUTABLE
    assert receipt.status == "installed"
    assert receipt.checksum_verified is True
    assert receipt.observed_sha256 == state_model.TLC_SHA256
    assert receipt.bindings["post_install_runtime_probe"]["returncode"] == 1
    assert f"exec '{java17.resolve()}' -cp " in launcher.read_text(
        encoding="utf-8"
    )


def test_legacy_tlc_launcher_requires_and_performs_atomic_rebind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(
        tmp_path / "java17" / "java",
        "17.0.12",
        runtime_exit=1,
        runtime_output=TLC_HELP_OUTPUT,
    )
    install_root = tmp_path / "install"
    jar = (
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    )
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"reviewed-fixture")
    launcher = _write_executable(
        install_root / "bin" / state_model.TLC_EXECUTABLE,
        f'exec java -cp "{jar}" tlc2.TLC "$@"',
    )
    legacy_body = launcher.read_text(encoding="utf-8")
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )

    blocked = state_model.ensure_tlc(
        yes=False,
        strict=True,
        install_root=install_root,
        java_executable=java17,
    )

    assert blocked.status == "blocked"
    assert "launcher_rebind_required" in blocked.reason_codes
    assert launcher.read_text(encoding="utf-8") == legacy_body

    repaired = state_model.ensure_tlc(
        yes=True,
        strict=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert repaired.status == "installed"
    assert repaired.phase == "launcher_rebound"
    assert f"exec '{java17.resolve()}' -cp " in launcher.read_text(
        encoding="utf-8"
    )


def test_strict_false_preserves_runnable_nonlocked_existing_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    external = tmp_path / "external"
    _write_executable(
        external / state_model.TLC_EXECUTABLE,
        f"cat <<'EOF'\n{TLC_HELP_OUTPUT.rstrip()}\nEOF\nexit 1",
    )
    _write_executable(
        external / state_model.APALACHE_EXECUTABLE,
        'echo "Apalache 9.9.9"',
    )
    monkeypatch.setenv("PATH", f"{external}:/usr/bin:/bin")

    tlc = state_model.ensure_tlc(
        yes=False,
        strict=False,
        install_root=tmp_path / "tlc-install",
        java_executable=java17,
    )
    apalache = state_model.ensure_apalache(
        yes=False,
        strict=False,
        install_root=tmp_path / "apalache-install",
        java_executable=java17,
    )

    assert tlc.status == "available"
    assert tlc.already_present is True
    assert apalache.status == "available"
    assert apalache.already_present is True


def test_apalache_post_install_probe_fails_before_launcher_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"
    previous_install = install_root / f"apalache-{state_model.APALACHE_VERSION}"
    previous_install.mkdir(parents=True)
    sentinel = previous_install / "previous-release"
    sentinel.write_text("preserve me", encoding="utf-8")
    old_launcher = _write_executable(
        install_root / "bin" / state_model.APALACHE_EXECUTABLE,
        'echo "previous launcher"',
    )
    previous_launcher = old_launcher.read_bytes()

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
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert old_launcher.read_bytes() == previous_launcher


def test_apalache_publication_failure_restores_previous_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"
    previous_install = install_root / f"apalache-{state_model.APALACHE_VERSION}"
    previous_install.mkdir(parents=True)
    sentinel = previous_install / "previous-release"
    sentinel.write_text("preserve me", encoding="utf-8")

    def fake_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"reviewed-archive")
        return True, "b" * 64

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
    monkeypatch.setattr(
        state_model,
        "_commit_staged_files",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected launcher publication failure")
        ),
    )

    with pytest.raises(OSError, match="injected launcher"):
        state_model.ensure_apalache(
            yes=True,
            strict=False,
            force=True,
            install_root=install_root,
            java_executable=java17,
            test_mode=True,
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve me"


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

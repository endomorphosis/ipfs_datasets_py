"""Runtime dependency regressions for the TLC/Apalache installer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import zipfile
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


def _write_tlc_jar(
    path: Path,
    *,
    release_tag: str = state_model.TLC_RELEASE_TAG,
    short_revision: str = state_model.TLC_REVISION,
    full_revision: str | None = None,
) -> Path:
    """Write the reviewed TLC manifest fields into a compact JAR fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_full_revision = full_revision or (
        short_revision + "0" * (40 - len(short_revision))
    )
    manifest = (
        "Manifest-Version: 1.0\r\n"
        "Implementation-Title: TLA+ Tools\r\n"
        "Main-class: tlc2.TLC\r\n"
        f"X-Git-Tag: build-fixture;{release_tag}\r\n"
        f"X-Git-Revision: {resolved_full_revision}\r\n"
        f"X-Git-ShortRevision: {short_revision}\r\n"
        "\r\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", manifest)
    return path


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
    assert probe.command == (str(apalache), "version")


def test_apalache_probe_does_not_fall_back_to_noncanonical_flags(
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    apalache = _write_executable(
        tmp_path / "apalache-mc",
        (
            'if [ "${1:-}" = "version" ]; then exit 1; fi\n'
            'echo "0.58.3"'
        ),
    )

    probe = state_model.probe_apalache_runtime(
        str(apalache),
        java_executable=java17,
    )

    assert probe.command == (str(apalache), "version")
    assert probe.usable is False
    assert probe.reason_code == "runtime_probe_nonzero_exit"


def test_apalache_probe_requires_exact_canonical_version_output(
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    prefixed = _write_executable(
        tmp_path / "prefixed" / "apalache-mc",
        'echo "Apalache 0.58.3"',
    )
    canonical = _write_executable(
        tmp_path / "canonical" / "apalache-mc",
        'echo "0.58.3"',
    )

    rejected = state_model.probe_apalache_runtime(
        str(prefixed),
        java_executable=java17,
    )
    accepted = state_model.probe_apalache_runtime(
        str(canonical),
        java_executable=java17,
    )

    assert rejected.usable is False
    assert rejected.reason_code == "runtime_version_unreadable"
    assert accepted.usable is True
    assert accepted.output == state_model.APALACHE_VERSION


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


def test_tlc_jar_manifest_identity_reads_reviewed_release_bindings(
    tmp_path: Path,
) -> None:
    jar = _write_tlc_jar(tmp_path / state_model.TLC_JAR_NAME)

    identity = state_model.read_tlc_jar_manifest_identity(jar)

    assert identity.valid is True
    assert identity.release_tag == state_model.TLC_RELEASE_TAG
    assert identity.short_revision == state_model.TLC_REVISION
    assert identity.full_revision is not None
    assert identity.full_revision.startswith(state_model.TLC_REVISION)


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        (
            {"release_tag": "v9.9.9"},
            "tlc_jar_release_tag_mismatch",
        ),
        (
            {"short_revision": "deadbee"},
            "tlc_jar_short_revision_mismatch",
        ),
        (
            {
                "short_revision": state_model.TLC_REVISION,
                "full_revision": "f" * 40,
            },
            "tlc_jar_full_revision_invalid",
        ),
    ],
)
def test_tlc_jar_manifest_identity_rejects_unreviewed_bindings(
    overrides: dict[str, str],
    reason_code: str,
    tmp_path: Path,
) -> None:
    jar = _write_tlc_jar(
        tmp_path / state_model.TLC_JAR_NAME,
        **overrides,
    )

    identity = state_model.read_tlc_jar_manifest_identity(jar)

    assert identity.valid is False
    assert identity.reason_code == reason_code


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


@pytest.mark.parametrize(
    ("digest", "is_checksummed"),
    [
        ("", False),
        ("0" * 64, True),
    ],
)
def test_blank_or_alternate_apalache_lock_digest_fails_closed(
    digest: str,
    is_checksummed: bool,
) -> None:
    lock = {
        "managed_pin_versions": {"apalache": state_model.APALACHE_VERSION},
        "tools": [
            {
                "tool_id": "apalache",
                "pins": [
                    {
                        "tool_id": "apalache",
                        "version": state_model.APALACHE_VERSION,
                        "platform": "any",
                        "artifact_url": (
                            "https://example.invalid/apalache-reviewed.tgz"
                        ),
                        "sha256": digest,
                        "is_checksummed": is_checksummed,
                    }
                ],
            }
        ],
    }

    with pytest.raises(state_model.StateModelInstallerError, match="digest"):
        state_model.select_strict_pin("apalache", lock=lock)


def test_tlc_rejects_downloader_that_lies_about_observed_digest(
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

    def lying_download(url: str, destination: Path, **kwargs: object):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"tampered payload")
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", lying_download)
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
    assert receipt.phase == "download"
    assert "download_or_checksum_failed" in receipt.reason_codes
    assert not (
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    ).exists()
    assert not (install_root / "bin" / state_model.TLC_EXECUTABLE).exists()


def test_tlc_rejects_digest_accepted_jar_with_wrong_manifest_identity(
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
        _write_tlc_jar(destination, release_tag="v9.9.9")
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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
    assert receipt.phase == "artifact_identity"
    assert "jar_manifest_identity_failed" in receipt.reason_codes
    assert "tlc_jar_release_tag_mismatch" in receipt.reason_codes
    assert not (
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    ).exists()


def test_download_artifact_uses_unique_partial_paths_and_cleans_them(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = b"reviewed artifact fixture"
    digest = state_model.content_sha256_bytes(payload)
    partial_paths: list[Path] = []
    original_named_temporary_file = state_model.tempfile.NamedTemporaryFile

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return payload

    def recording_temporary_file(*args, **kwargs):
        handle = original_named_temporary_file(*args, **kwargs)
        partial_paths.append(Path(handle.name))
        return handle

    monkeypatch.setattr(state_model, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        state_model.tempfile,
        "NamedTemporaryFile",
        recording_temporary_file,
    )
    destination = tmp_path / "downloads" / "artifact.bin"

    first = state_model.download_artifact(
        "https://example.invalid/artifact.bin",
        destination,
        sha256=digest,
    )
    destination.unlink()
    second = state_model.download_artifact(
        "https://example.invalid/artifact.bin",
        destination,
        sha256=digest,
    )

    assert first == second == (True, digest)
    assert len(partial_paths) == 2
    assert partial_paths[0] != partial_paths[1]
    assert all(not path.exists() for path in partial_paths)


def test_launcher_identity_requires_exact_complete_bytes(tmp_path: Path) -> None:
    target = _write_executable(tmp_path / "payload", 'echo "payload"')
    expected = state_model._launcher_body(target)
    launcher = tmp_path / "launcher"
    launcher.write_text(
        expected + "# contains every expected token but changes the program\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    identity = state_model._launcher_identity(
        launcher,
        expected_body=expected,
    )

    assert identity["executable"] is True
    assert identity["observed_sha256"] != identity["expected_sha256"]
    assert identity["structural_match"] is False


@pytest.mark.skipif(os.name == "nt", reason="symlink semantics differ on Windows")
def test_launcher_identity_rejects_symlink_even_with_exact_bytes(
    tmp_path: Path,
) -> None:
    target = _write_executable(tmp_path / "payload", 'echo "payload"')
    expected = state_model._launcher_body(target)
    real_launcher = tmp_path / "real-launcher"
    real_launcher.write_text(expected, encoding="utf-8")
    real_launcher.chmod(0o755)
    launcher = tmp_path / "launcher"
    launcher.symlink_to(real_launcher)

    identity = state_model._launcher_identity(
        launcher,
        expected_body=expected,
    )

    assert identity["observed_sha256"] == identity["expected_sha256"]
    assert identity["present"] is False
    assert identity["structural_match"] is False


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
        _write_tlc_jar(destination)
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
@pytest.mark.parametrize("target_exists", [True, False])
def test_atomic_file_publication_restores_live_and_broken_symlinks_exactly(
    target_exists: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / ("target" if target_exists else "missing-target")
    if target_exists:
        target.write_bytes(b"linked-payload")
    first = tmp_path / "final" / "first"
    second = tmp_path / "final" / "second"
    first.parent.mkdir(parents=True)
    link_text = os.path.relpath(target, first.parent)
    first.symlink_to(link_text)
    second.write_bytes(b"old-second")
    staged_first = tmp_path / "staged" / "first"
    staged_second = tmp_path / "staged" / "second"
    staged_first.parent.mkdir(parents=True)
    staged_first.write_bytes(b"new-first")
    staged_second.write_bytes(b"new-second")
    original_replace = Path.replace

    def fail_second(source: Path, destination: Path):
        if source == staged_second:
            raise OSError("injected publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second)

    with pytest.raises(OSError, match="injected"):
        state_model._commit_staged_files(
            ((staged_first, first), (staged_second, second)),
            backup_dir=tmp_path / "backups",
        )

    assert first.is_symlink()
    assert os.readlink(first) == link_text
    assert first.exists() is target_exists
    assert second.read_bytes() == b"old-second"


@pytest.mark.skipif(os.name == "nt", reason="POSIX thread-lock fixture")
def test_concurrent_failed_publication_cannot_rollback_later_generation(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "install"
    first = install_root / "bin" / "first"
    second = install_root / "bin" / "second"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")
    failing_validation_started = threading.Event()
    release_failing_validation = threading.Event()
    succeeding_lock_acquired = threading.Event()
    failures: list[BaseException] = []

    def publish(token: str, *, fail_validation: bool) -> None:
        try:
            staging = tmp_path / f"staging-{token}"
            staged_first = staging / "first"
            staged_second = staging / "second"
            staging.mkdir(parents=True)
            staged_first.write_text(f"{token}-first", encoding="utf-8")
            staged_second.write_text(f"{token}-second", encoding="utf-8")
            with state_model.installation_lock(install_root):
                if not fail_validation:
                    succeeding_lock_acquired.set()

                def validate() -> bool:
                    if fail_validation:
                        failing_validation_started.set()
                        if not release_failing_validation.wait(timeout=5):
                            raise TimeoutError("review fixture did not release")
                        return False
                    return True

                state_model._commit_staged_files(
                    ((staged_first, first), (staged_second, second)),
                    backup_dir=staging / "backups",
                    post_publish_validate=validate,
                )
        except state_model.StateModelPublicationValidationError:
            if not fail_validation:
                failures.append(AssertionError("successful publication rolled back"))
        except BaseException as exc:  # noqa: BLE001 - thread failure is re-raised below
            failures.append(exc)

    failing = threading.Thread(
        target=publish,
        kwargs={"token": "failing", "fail_validation": True},
    )
    succeeding = threading.Thread(
        target=publish,
        kwargs={"token": "success", "fail_validation": False},
    )
    failing.start()
    assert failing_validation_started.wait(timeout=5)
    succeeding.start()
    time.sleep(0.05)
    assert not succeeding_lock_acquired.is_set()
    release_failing_validation.set()
    failing.join(timeout=5)
    succeeding.join(timeout=5)

    assert not failing.is_alive()
    assert not succeeding.is_alive()
    assert failures == []
    assert first.read_text(encoding="utf-8") == "success-first"
    assert second.read_text(encoding="utf-8") == "success-second"


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
        _write_tlc_jar(destination)
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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
    identity = state_model.managed_tlc_identity(
        install_root,
        java_executable=java17,
    )
    assert identity["usable"] is True
    launcher.write_text(
        launcher.read_text(encoding="utf-8") + "# tampered\n",
        encoding="utf-8",
    )
    assert (
        state_model.managed_tlc_identity(
            install_root,
            java_executable=java17,
        )["usable"]
        is False
    )


def test_relocated_legacy_tlc_manifest_derives_release_only_from_locked_jar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployment_root = tmp_path / "immutable"
    install_root = deployment_root / "release-1" / "provers"
    java17 = _fake_java(
        install_root / "jdk-17" / "bin" / "java",
        "17.0.12",
    )
    jar = _write_tlc_jar(
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    )
    fixture_digest = state_model.content_sha256(jar)
    monkeypatch.setattr(state_model, "TLC_SHA256", fixture_digest)
    for name in (
        state_model.TLC_EXECUTABLE,
        "tlc2",
        "tla2tools",
    ):
        state_model.write_launcher(
            name,
            jar,
            install_root=install_root,
            environment={"TLA2TOOLS_JAR": str(jar)},
            java_jar=jar,
            java_main="tlc2.TLC",
            java_executable=java17,
        )

    previous_root = Path("/srv/reviewed/state-model-runtime")
    manifest = {
        "schema_version": "state-model-managed-runtime/v1",
        "tool_id": "tlc",
        "version": state_model.TLC_VERSION,
        "artifact_path": str(previous_root / jar.relative_to(install_root)),
        "artifact_sha256": fixture_digest,
        "payload_path": str(previous_root / jar.relative_to(install_root)),
        "payload_sha256": fixture_digest,
        "java_executable": str(
            previous_root / java17.relative_to(install_root)
        ),
        "launchers": {
            name: {
                "path": str(previous_root / "bin" / name),
                "sha256": "a" * 64,
            }
            for name in (
                state_model.TLC_EXECUTABLE,
                "tlc2",
                "tla2tools",
            )
        },
    }
    manifest_path = install_root / "manifests" / "tlc.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    managed = state_model.managed_tlc_identity(
        install_root,
        java_executable=java17,
    )
    assert managed["manifest_valid"] is False
    assert managed["jar_manifest_valid"] is True

    relocated = state_model.validate_relocated_managed_manifest(
        install_root,
        managed_identity=managed,
        approved_root_prefixes=(deployment_root,),
    )

    assert relocated["valid"] is True
    assert relocated["legacy_tlc_manifest"] is True
    assert relocated["previous_root"] == str(previous_root)
    assert (
        relocated["release_identity_source"]
        == "checksum_bound_tlc_jar_manifest"
    )

    partially_populated = dict(manifest)
    partially_populated["release_tag"] = state_model.TLC_RELEASE_TAG
    manifest_path.write_text(
        json.dumps(partially_populated),
        encoding="utf-8",
    )
    rejected_partial = state_model.validate_relocated_managed_manifest(
        install_root,
        managed_identity=managed,
        approved_root_prefixes=(deployment_root,),
    )
    assert rejected_partial["valid"] is False
    assert (
        "relocated_state_manifest_field_population_invalid"
        in rejected_partial["failures"]
    )

    wrong_suffix = dict(manifest)
    wrong_suffix["payload_path"] = str(previous_root / "other" / jar.name)
    manifest_path.write_text(json.dumps(wrong_suffix), encoding="utf-8")
    rejected_suffix = state_model.validate_relocated_managed_manifest(
        install_root,
        managed_identity=managed,
        approved_root_prefixes=(deployment_root,),
    )
    assert rejected_suffix["valid"] is False
    assert (
        "relocated_state_payload_suffix_mismatch"
        in rejected_suffix["failures"]
    )

    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    jar.write_bytes(jar.read_bytes() + b"tampered")
    rejected_jar = state_model.validate_relocated_managed_manifest(
        install_root,
        managed_identity=managed,
        approved_root_prefixes=(deployment_root,),
    )
    assert rejected_jar["valid"] is False
    assert (
        "relocated_state_artifact_digest_mismatch"
        in rejected_jar["failures"]
    )
    assert (
        "relocated_state_tlc_release_identity_mismatch"
        in rejected_jar["failures"]
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
def test_symlinked_managed_tlc_jar_is_replaced_before_success(
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
    external_jar = tmp_path / "external" / state_model.TLC_JAR_NAME
    external_jar.parent.mkdir(parents=True)
    external_jar.write_bytes(b"external-reviewed-fixture")
    managed_jar = (
        install_root
        / "tlc"
        / state_model.TLC_VERSION
        / state_model.TLC_JAR_NAME
    )
    managed_jar.parent.mkdir(parents=True)
    managed_jar.symlink_to(external_jar)
    downloads: list[Path] = []

    def fake_download(url: str, destination: Path, **kwargs: object):
        downloads.append(destination)
        _write_tlc_jar(destination)
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        state_model,
        "which_executable",
        lambda name, **kwargs: (
            None if name == state_model.TLC_EXECUTABLE else str(name)
        ),
    )

    receipt = state_model.ensure_tlc(
        yes=True,
        strict=False,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert downloads
    assert receipt.status == "installed"
    assert receipt.installed is True
    assert not managed_jar.is_symlink()
    assert managed_jar.read_bytes().startswith(b"PK")
    identity = state_model.managed_tlc_identity(
        install_root,
        java_executable=java17,
    )
    assert identity["usable"] is True
    assert receipt.bindings["post_publication_managed_identity"]["usable"] is True


def test_tlc_post_publication_identity_failure_rolls_back_complete_bundle(
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
    jar.write_bytes(b"old-jar")
    old_paths = {
        install_root / "bin" / "tlc": b"old-tlc",
        install_root / "bin" / "tlc2": b"old-tlc2",
        install_root / "bin" / "tla2tools": b"old-tla2tools",
        install_root / "manifests" / "tlc.json": b"old-manifest",
    }
    for path, payload in old_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def fake_download(url: str, destination: Path, **kwargs: object):
        _write_tlc_jar(destination)
        return True, state_model.TLC_SHA256

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        state_model,
        "managed_tlc_identity",
        lambda *args, **kwargs: {"usable": False},
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
    assert receipt.phase == "publication_validation"
    assert receipt.installed is False
    assert "post_publication_identity_failed" in receipt.reason_codes
    assert jar.read_bytes() == b"old-jar"
    for path, payload in old_paths.items():
        assert path.read_bytes() == payload


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
    _write_tlc_jar(jar)
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
    assert "managed_identity_repair_required" in blocked.reason_codes
    assert launcher.read_text(encoding="utf-8") == legacy_body

    repaired = state_model.ensure_tlc(
        yes=True,
        strict=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert repaired.status == "installed"
    assert repaired.phase == "managed_identity_repaired"
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
        'echo "9.9.9"',
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
        return True, state_model.APALACHE_SHA256

    def fake_extract(archive: Path, destination: Path) -> None:
        _write_executable(
            destination / "apalache-0.58.3" / "bin" / "apalache-mc",
            'echo "0.58.3" >&2\nexit 1',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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
        return True, state_model.APALACHE_SHA256

    def fake_extract(archive: Path, destination: Path) -> None:
        _write_executable(
            destination / "apalache-0.58.3" / "bin" / "apalache-mc",
            'echo "0.58.3"',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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
        return True, state_model.APALACHE_SHA256

    def fake_extract(archive: Path, destination: Path) -> None:
        _write_executable(
            destination / "apalache-0.58.3" / "bin" / "apalache-mc",
            'echo "0.58.3"',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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
    identity = state_model.managed_apalache_identity(
        install_root,
        java_executable=java17,
    )
    assert identity["usable"] is True
    payload = Path(identity["payload_path"])
    payload.chmod(0o644)
    assert (
        state_model.managed_apalache_identity(
            install_root,
            java_executable=java17,
        )["usable"]
        is False
    )
    payload.chmod(0o755)
    payload.write_text(
        payload.read_text(encoding="utf-8") + "# tampered\n",
        encoding="utf-8",
    )
    assert (
        state_model.managed_apalache_identity(
            install_root,
            java_executable=java17,
        )["usable"]
        is False
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
@pytest.mark.parametrize("symlink_kind", ["archive", "payload"])
def test_symlinked_apalache_archive_or_payload_is_replaced_before_success(
    symlink_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"
    archive = (
        install_root
        / "downloads"
        / f"apalache-{state_model.APALACHE_VERSION}.tgz"
    )
    distribution = install_root / f"apalache-{state_model.APALACHE_VERSION}"
    payload = (
        distribution
        / f"apalache-{state_model.APALACHE_VERSION}"
        / "bin"
        / state_model.APALACHE_EXECUTABLE
    )
    archive.parent.mkdir(parents=True)
    payload.parent.mkdir(parents=True)
    if symlink_kind == "archive":
        external_archive = tmp_path / "external" / archive.name
        external_archive.parent.mkdir(parents=True)
        external_archive.write_bytes(b"external-archive")
        archive.symlink_to(external_archive)
        _write_executable(payload, 'echo "0.58.3"')
    else:
        archive.write_bytes(b"reviewed-archive")
        external_payload = _write_executable(
            tmp_path / "external" / state_model.APALACHE_EXECUTABLE,
            'echo "0.58.3"',
        )
        payload.symlink_to(external_payload)
    downloads: list[Path] = []

    def fake_download(url: str, destination: Path, **kwargs: object):
        downloads.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"new-reviewed-archive")
        return True, state_model.APALACHE_SHA256

    def fake_extract(archive_path: Path, destination: Path) -> None:
        _write_executable(
            destination
            / f"apalache-{state_model.APALACHE_VERSION}"
            / "bin"
            / state_model.APALACHE_EXECUTABLE,
            'echo "0.58.3"',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
    monkeypatch.setattr(state_model, "_safe_extract_tar", fake_extract)
    monkeypatch.setattr(
        state_model,
        "authorize_plugin_install",
        lambda *args, **kwargs: None,
    )

    receipt = state_model.ensure_apalache(
        yes=True,
        strict=True,
        install_root=install_root,
        java_executable=java17,
        test_mode=True,
    )

    assert downloads
    assert receipt.status == "installed"
    assert receipt.installed is True
    identity = state_model.managed_apalache_identity(
        install_root,
        java_executable=java17,
    )
    assert identity["usable"] is True
    assert not Path(identity["artifact_path"]).is_symlink()
    assert not Path(identity["payload_path"]).is_symlink()
    assert receipt.bindings["post_publication_managed_identity"]["usable"] is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
def test_apalache_publication_failure_restores_broken_distribution_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    java17 = _fake_java(tmp_path / "java17" / "java", "17.0.12")
    install_root = tmp_path / "install"
    destination = install_root / f"apalache-{state_model.APALACHE_VERSION}"
    destination.parent.mkdir(parents=True)
    link_text = "../missing-apalache-distribution"
    destination.symlink_to(link_text, target_is_directory=True)

    def fake_download(url: str, staged: Path, **kwargs: object):
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"reviewed-archive")
        return True, state_model.APALACHE_SHA256

    def fake_extract(archive_path: Path, extracted: Path) -> None:
        _write_executable(
            extracted
            / f"apalache-{state_model.APALACHE_VERSION}"
            / "bin"
            / state_model.APALACHE_EXECUTABLE,
            'echo "0.58.3"',
        )

    monkeypatch.setattr(state_model, "download_artifact", fake_download)
    monkeypatch.setattr(state_model, "verify_sha256", lambda *args: True)
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

    assert destination.is_symlink()
    assert os.readlink(destination) == link_text
    assert not destination.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX subprocess ordering fixture")
def test_installation_lock_serializes_independent_processes(tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    event_log = tmp_path / "events.log"
    package_root = Path(state_model.__file__).resolve().parents[4]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(package_root),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    program = """\
import os
import sys
import time
from pathlib import Path
from ipfs_datasets_py.logic.backends.installers import state_model

root = Path(sys.argv[1])
event_log = Path(sys.argv[2])
token = sys.argv[3]
with state_model.installation_lock(root):
    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(f"start:{token}\\n")
        handle.flush()
        os.fsync(handle.fileno())
    time.sleep(0.25)
    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(f"end:{token}\\n")
        handle.flush()
        os.fsync(handle.fileno())
"""

    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(install_root),
            str(event_log),
            "first",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if event_log.is_file() and "start:first" in event_log.read_text(
            encoding="utf-8"
        ):
            break
        time.sleep(0.01)
    else:
        first.kill()
        stdout, stderr = first.communicate(timeout=5)
        pytest.fail(f"first lock process did not start: {stdout}\n{stderr}")

    second = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(install_root),
            str(event_log),
            "second",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_stdout, first_stderr = first.communicate(timeout=10)
    second_stdout, second_stderr = second.communicate(timeout=10)

    assert first.returncode == 0, f"{first_stdout}\n{first_stderr}"
    assert second.returncode == 0, f"{second_stdout}\n{second_stderr}"
    assert event_log.read_text(encoding="utf-8").splitlines() == [
        "start:first",
        "end:first",
        "start:second",
        "end:second",
    ]

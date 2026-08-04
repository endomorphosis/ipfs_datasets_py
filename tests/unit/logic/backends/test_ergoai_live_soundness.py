"""Adversarial checks for bounded, provenance-bound ErgoAI execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.installers import advisors
from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ErgoAIWrapper


def _write_executable(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_elf(machine: int) -> bytes:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header)


def _semantic_runner_source() -> str:
    """Return a tiny deterministic stand-in for the live semantic protocol."""

    return r'''#!/usr/bin/python3
import os
import pathlib
import re
import sys
import time

if "--version" in sys.argv:
    print("ErgoAI 3.0")
    raise SystemExit(0)

capture_path = os.environ.get("FVT_CAPTURE_RUNTIME_PATH")
if capture_path:
    pathlib.Path(capture_path).write_text(os.environ.get("PATH", ""))

commands = sys.stdin.read()
match = re.search(r"load\{'([^']+)'\}", commands)
program = pathlib.Path(match.group(1)).read_text() if match else ""
if "this is not" in program:
    print("++Error: syntax error")
    raise SystemExit(1)
if "fvt_loop" in program:
    time.sleep(5)
    raise SystemExit(0)
if "fvt_ergo_resource_marker" in program:
    sys.stdout.write("R" * 1048576)
    sys.stdout.flush()
    time.sleep(5)
    raise SystemExit(0)

if "fvt_ergo_unrelated" in commands:
    verdict = "No"
elif "fvt_ergo_contradiction" in program:
    verdict = "Yes" if "\\neg fvt_ergo_subject" in commands else "No"
elif "fvt_ergo_absent" in commands or "fvt_ergo_mutated" in program:
    verdict = "No"
else:
    verdict = "Yes"
print(f"Times (nanoseconds): {time.time_ns()}")
print(verdict)
'''


def test_hardened_ergoai_contract_symbols_are_public() -> None:
    expected = {
        "ERGOAI_EXECUTABLES",
        "ERGOAI_CONFIG_SOURCE_SHA256",
        "ERGOAI_CONFIG_HARDENED_SHA256",
        "ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT",
        "ERGOAI_REQUIRED_ABSOLUTE_COMMANDS",
        "ERGOAI_VERSIONED_BUILD_COMMANDS",
        "ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION",
        "ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS",
        "ERGOAI_BOUND_RUNTIME_PATH_MODEL",
        "ERGOAI_IDENTITY_MAX_BYTES",
        "ERGOAI_ACQUISITION_CHUNK_BYTES",
        "ergoai_safe_temporary_directory",
        "ergoai_managed_runtime_subprocess_env",
    }

    assert expected <= set(advisors.__all__)
    assert all(hasattr(advisors, name) for name in expected)


def test_offline_environment_has_no_direct_proxy_fallback() -> None:
    env = advisors.ergoai_offline_subprocess_env(
        {
            "PATH": os.environ.get("PATH", ""),
            "HTTP_PROXY": "https://usable.invalid:8443",
            "NO_PROXY": "*",
        }
    )

    for key in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    ):
        assert env[key] == "http://127.0.0.1:9"
    assert env["NO_PROXY"] == env["no_proxy"] == ""
    assert env["FORMAL_VERIFICATION_FORBID_NETWORK"] == "1"
    assert env["FORMAL_VERIFICATION_FORBID_INSTALL"] == "1"


def test_bounded_runner_enforces_output_and_timeout_while_streaming(
    tmp_path: Path,
) -> None:
    flood = _write_executable(
        tmp_path / "flood",
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdin.read()\n"
        "sys.stdout.write('X' * 1048576)\n"
        "sys.stdout.flush()\n"
        "time.sleep(5)\n",
    )
    bounded = advisors.run_bounded_ergoai_process(
        flood,
        input_text="query\n",
        timeout=2,
        max_output_bytes=257,
        env=advisors.ergoai_offline_subprocess_env(),
    )

    assert bounded["termination_reason"] == "output_limit"
    assert bounded["resource_bound_enforced"] is True
    assert bounded["captured_output_bytes"] == 257
    assert len(bounded["output_text"].encode()) == 257
    assert bounded["observed_output_bytes"] > 257
    assert bounded["output_digest_complete"] is False

    sleeper = _write_executable(
        tmp_path / "sleeper",
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdin.read()\n"
        "time.sleep(5)\n",
    )
    timed = advisors.run_bounded_ergoai_process(
        sleeper,
        input_text="query\n",
        timeout=0.05,
        max_output_bytes=1024,
        env=advisors.ergoai_offline_subprocess_env(),
    )

    assert timed["termination_reason"] == "timeout"
    assert timed["timed_out"] is True
    assert timed["resource_bound_enforced"] is False


def test_bounded_runner_does_not_block_while_child_ignores_large_stdin(
    tmp_path: Path,
) -> None:
    ignores_stdin = _write_executable(
        tmp_path / "ignores-stdin",
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(30)\n",
    )

    started = time.monotonic()
    result = advisors.run_bounded_ergoai_process(
        ignores_stdin,
        input_text="X" * (4 * 1024 * 1024),
        timeout=0.05,
        max_output_bytes=1024,
        env=advisors.ergoai_offline_subprocess_env(),
    )

    assert result["termination_reason"] == "timeout"
    assert result["timed_out"] is True
    assert time.monotonic() - started < 2.5


@pytest.mark.skipif(os.name != "posix", reason="process-group contract is POSIX-only")
def test_bounded_runner_kills_term_ignoring_descendant_after_leader_exits(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "descendant.pid"
    launcher = _write_executable(
        tmp_path / "process-tree",
        r'''#!/usr/bin/env python3
import os
import pathlib
import signal
import subprocess
import sys
import time

pid_path = pathlib.Path(sys.argv[1])
if len(sys.argv) == 3:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pid_path.write_text(str(os.getpid()))
    time.sleep(30)
else:
    subprocess.Popen([sys.executable, __file__, str(pid_path), "child"])
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    deadline = time.monotonic() + 2
    while not pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(30)
''',
    )

    result = advisors.run_bounded_ergoai_process(
        launcher,
        args=(str(pid_path),),
        input_text="",
        timeout=0.4,
        max_output_bytes=1024,
        env=advisors.ergoai_offline_subprocess_env(),
    )

    assert result["termination_reason"] == "timeout"
    assert pid_path.is_file()
    descendant_pid = int(pid_path.read_text(encoding="utf-8"))

    def descendant_is_active() -> bool:
        status_path = Path("/proc") / str(descendant_pid) / "stat"
        try:
            # A killed orphan may remain briefly as a zombie awaiting init;
            # it is no longer an executing descendant.
            return status_path.read_text(encoding="utf-8").split()[2] != "Z"
        except (FileNotFoundError, IndexError, OSError):
            return False

    active = True
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        active = descendant_is_active()
        if not active:
            break
        time.sleep(0.02)
    if active:
        # Keep a regression failure from leaking the adversarial child.
        try:
            os.kill(descendant_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert active is False


def test_version_probes_are_output_bounded(tmp_path: Path) -> None:
    flood = _write_executable(
        tmp_path / "version-flood",
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdin.read()\n"
        "sys.stdout.write('ErgoAI 3.0\\n' + ('X' * 1048576))\n"
        "sys.stdout.flush()\n"
        "time.sleep(5)\n",
    )

    assert (
        advisors.read_ergoai_version_banner(
            str(flood),
            timeout=1,
            max_output_bytes=128,
        )
        is None
    )


def test_live_matrix_uses_semantic_replay_and_real_bounds(tmp_path: Path) -> None:
    runner = _write_executable(
        tmp_path / "ergoai",
        _semantic_runner_source(),
    )

    evidence = advisors.run_ergoai_semantic_checks(
        runner,
        timeout=1,
        include_extended=True,
        bound_timeout_seconds=0.05,
        max_output_bytes=256,
    )

    assert evidence["passed"] is True
    assert evidence["checks"]["contradiction"]["passed"] is True
    assert evidence["checks"]["contradiction"]["non_explosion"]["passed"] is True
    assert evidence["checks"]["timeout"]["timed_out"] is True
    assert evidence["checks"]["timeout"]["terminating_control"]["passed"] is True
    assert evidence["checks"]["resource_bound"]["resource_bound_enforced"] is True
    assert evidence["checks"]["resource_bound"]["bounded_control"]["passed"] is True
    assert evidence["replay_bound"] is True
    assert (
        evidence["checks"]["entailment"]["semantic_outcome_digest_sha256"]
        == evidence["checks"]["replay"]["semantic_outcome_digest_sha256"]
    )
    assert (
        evidence["checks"]["entailment"]["output_digest_sha256"]
        != evidence["checks"]["replay"]["output_digest_sha256"]
    )


def test_resealed_semantic_forgery_is_rejected(tmp_path: Path) -> None:
    runner = _write_executable(tmp_path / "ergoai", _semantic_runner_source())
    evidence = advisors.run_ergoai_semantic_checks(
        runner,
        timeout=1,
        include_extended=True,
        bound_timeout_seconds=0.05,
        max_output_bytes=256,
    )
    valid, reasons, _checks = advisors._validate_recorded_ergoai_semantics(
        evidence
    )
    assert valid is True
    assert reasons == []

    forged = json.loads(json.dumps(evidence))
    forged_program_digest = "0" * 64
    for name in ("entailment", "positive", "replay"):
        forged["checks"][name]["program_digest_sha256"] = forged_program_digest
    forged["normalized_evidence_digest_sha256"] = (
        advisors._ergoai_semantic_evidence_digest(
            forged["checks"],
            replay_bound=forged["replay_bound"],
            passed=forged["passed"],
        )
    )

    valid, reasons, checks = advisors._validate_recorded_ergoai_semantics(forged)
    assert valid is False
    assert checks["normalized_digest"] is True
    assert "semantic_checks_entailment_mismatch" in reasons
    assert "semantic_checks_replay_mismatch" in reasons


def test_identity_loader_fails_closed_for_malformed_large_and_symlinked_data(
    tmp_path: Path,
) -> None:
    root = tmp_path / "managed"
    identity_path = root / "advisors" / "ergoai" / "3.0" / "identity.json"
    identity_path.parent.mkdir(parents=True)
    launcher = _write_executable(
        root / "bin" / "ergoai",
        "#!/bin/sh\nprintf 'ErgoAI 3.0\\n'\n",
    )

    malformed_documents = (
        b"[]",
        b'{"launcher_digests": 7, "release_artifact_path": []}',
        b"{not-json",
        b" " * (advisors.ERGOAI_IDENTITY_MAX_BYTES + 1),
    )
    for document in malformed_documents:
        identity_path.write_bytes(document)
        result = advisors.probe_ergoai_identity(
            executable=str(launcher),
            install_root=root,
            require_managed_vendor=True,
            platform_key="linux-x86_64",
        )
        assert result["managed_vendor_provenance_verified"] is False
        assert result["probe_error"] == "managed_vendor_provenance_unverified"

    identity_path.unlink()
    external_identity = tmp_path / "external-identity.json"
    external_identity.write_text("{}", encoding="utf-8")
    identity_path.symlink_to(external_identity)
    symlinked = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert symlinked["managed_vendor_provenance_verified"] is False
    assert "managed_identity_manifest_unsafe" in symlinked["reason_codes"]


def test_acquisition_rejects_size_overrun_and_bad_content_length(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = b"abc"
    pin = advisors.ToolPin(
        tool_id=advisors.TOOL_ERGOAI,
        version=advisors.ERGOAI_VERSION,
        platform="linux-x86_64",
        artifact_url="https://example.invalid/ergoAI_3.0.run",
        sha256=hashlib.sha256(expected).hexdigest(),
        identity_kind="immutable_release_tag",
        license="Apache-2.0",
        source="https://github.com/ErgoAI/ErgoEngine",
        is_checksummed=True,
        requires_checksum_at_install=True,
        release_tag=advisors.ERGOAI_RELEASE_TAG,
        artifact_size_bytes=len(expected),
    )
    oversized_source = tmp_path / "oversized.run"
    oversized_source.write_bytes(expected + b"x")
    local_destination = tmp_path / "local" / "ergoAI_3.0.run"

    local_result = advisors._copy_or_download_ergoai_artifact(
        pin,
        local_destination,
        artifact_path=oversized_source,
        timeout=1,
    )
    assert local_result == (False, None, len(expected) + 1)
    assert not local_destination.exists()

    class WrongLengthResponse(io.BytesIO):
        headers = {"Content-Length": str(len(expected) + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        advisors,
        "urlopen",
        lambda *_args, **_kwargs: WrongLengthResponse(expected),
    )
    progress: list[tuple[str, str]] = []
    remote_destination = tmp_path / "remote" / "ergoAI_3.0.run"
    remote_result = advisors._copy_or_download_ergoai_artifact(
        pin,
        remote_destination,
        timeout=1,
        on_progress=lambda phase, message: progress.append((phase, message)),
    )
    assert remote_result == (False, None, None)
    assert not remote_destination.exists()
    assert any("Content-Length does not match" in message for _, message in progress)

    class HeaderlessOversizedResponse(io.BytesIO):
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        advisors,
        "urlopen",
        lambda *_args, **_kwargs: HeaderlessOversizedResponse(expected + b"x"),
    )
    progress.clear()
    overrun_destination = tmp_path / "overrun" / "ergoAI_3.0.run"
    overrun_result = advisors._copy_or_download_ergoai_artifact(
        pin,
        overrun_destination,
        timeout=1,
        on_progress=lambda phase, message: progress.append((phase, message)),
    )
    assert overrun_result == (False, None, None)
    assert not overrun_destination.exists()
    assert any("byte ceiling" in message for _, message in progress)


def test_acquisition_copy_enforces_wall_deadline() -> None:
    class SlowStream(io.BytesIO):
        def read1(self, size: int = -1) -> bytes:
            time.sleep(0.02)
            return super().read(size)

    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        advisors._copy_exact_ergoai_stream(
            SlowStream(b"abc"),
            io.BytesIO(),
            expected_size=3,
            deadline=time.monotonic() + 0.005,
        )


def test_unsafe_managed_paths_and_ambient_tmpdir_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    unsafe_tmp = str(tmp_path / "unsafe tmp';touch-pwned")
    monkeypatch.setenv("TMPDIR", unsafe_tmp)
    assert advisors.ergoai_safe_temporary_directory() == Path("/tmp")
    assert advisors._makeself_safe_path(tmp_path / "unsafe install [glob]") is False

    root = tmp_path / "managed"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    poisoned = root / "advisors"
    poisoned.symlink_to(external, target_is_directory=True)
    with pytest.raises(advisors.AdvisorInstallerError, match="unsafe managed"):
        advisors._ensure_safe_managed_directory(root, poisoned / "ergoai")
    assert not (external / "ergoai").exists()


def test_hermetic_materializers_refuse_symlinked_write_targets(
    tmp_path: Path,
) -> None:
    alias_root = tmp_path / "alias-root"
    alias_bin = alias_root / "advisors" / "ergoai" / "3.0" / "bin"
    alias_bin.mkdir(parents=True)
    external_file = tmp_path / "outside-launcher"
    external_file.write_text("do-not-overwrite\n", encoding="utf-8")
    (alias_bin / "runErgo.sh").symlink_to(external_file)

    with pytest.raises(
        advisors.AdvisorInstallerError,
        match="unsafe managed file destination",
    ):
        advisors.materialize_hermetic_ergoai(install_root=alias_root)
    assert external_file.read_text(encoding="utf-8") == "do-not-overwrite\n"

    path_root = tmp_path / "path-root"
    path_root.mkdir()
    external_bin = tmp_path / "outside-bin"
    external_bin.mkdir()
    (path_root / "bin").symlink_to(external_bin, target_is_directory=True)
    with pytest.raises(advisors.AdvisorInstallerError, match="unsafe managed"):
        advisors.materialize_hermetic_ergoai(install_root=path_root)
    assert list(external_bin.iterdir()) == []

    symai_root = tmp_path / "symai-root"
    symai_root.mkdir()
    external_advisors = tmp_path / "outside-advisors"
    external_advisors.mkdir()
    (symai_root / "advisors").symlink_to(
        external_advisors,
        target_is_directory=True,
    )
    with pytest.raises(advisors.AdvisorInstallerError, match="unsafe managed"):
        advisors.materialize_hermetic_symbolicai_marker(
            install_root=symai_root
        )
    assert list(external_advisors.iterdir()) == []


@pytest.mark.parametrize("surface", ("contract", "inventory"))
@pytest.mark.parametrize(
    ("field_path", "replacement"),
    (
        (
            (
                "optional_java_api_dependencies",
                "missing_optional_capabilities_do_not_block_core_ergoai",
            ),
            False,
        ),
        (("runtime_dependencies", "xsb"), "unbound-runtime"),
        (("lazy_install", "atomic"), False),
        (("identity_probe", "network"), True),
        (("config_hardening", "hardened_sha256"), "0" * 64),
        (
            ("bound_build_environment", "allowlisted_environment_keys"),
            [],
        ),
        (
            ("bound_runtime_environment_contract", "path_model"),
            "ambient-path/v0",
        ),
        (("runtime_execution_policy",), "ambient-runtime/v0"),
    ),
)
def test_strict_lock_rejects_ergoai_contract_surface_mutations(
    surface: str,
    field_path: tuple[str, ...],
    replacement: object,
) -> None:
    lock_path = advisors.resolve_lock_path()
    assert lock_path is not None
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if surface == "contract":
        target = next(
            item for item in lock["tools"] if item.get("tool_id") == "ergoai"
        )["deployment_contract"]
    else:
        target = lock["checksummed_release_inventory"]["ergoai"]
    for name in field_path[:-1]:
        target = target[name]
    target[field_path[-1]] = replacement

    with pytest.raises(
        advisors.AdvisorInstallerError,
        match="deployment lock ErgoAI contract mismatch",
    ):
        advisors.pins_for_tool(advisors.TOOL_ERGOAI, lock=lock)


def test_present_malformed_deployment_lock_does_not_fall_back(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "config" / "formal_verification_toolchains.lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{malformed", encoding="utf-8")

    with pytest.raises(
        advisors.AdvisorInstallerError,
        match="invalid formal-verification deployment lock",
    ):
        advisors.pins_for_tool(advisors.TOOL_ERGOAI, repo_root=tmp_path)


def test_build_dependency_identity_rejects_ambient_old_make(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_make = _write_executable(
        tmp_path / "make",
        "#!/bin/sh\nprintf 'GNU Make 3.70\\n'\n",
    )
    real_which = advisors.shutil.which

    def overridden_which(name: str):
        return str(old_make) if name == "make" else real_which(name)

    monkeypatch.setattr(advisors.shutil, "which", overridden_which)
    identity = advisors._ergoai_build_dependency_identity()

    assert identity["satisfied"] is False
    assert identity["version_mismatches"] == ["make"]
    assert identity["commands"]["make"]["observed_version"] == "3.70"


def test_managed_provenance_binds_exact_selected_executable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "managed"
    release = root / "downloads" / "ergoAI_3.0.run"
    distribution = (
        root
        / "advisors"
        / "ergoai"
        / "3.0"
        / "vendor-test-relocatable-v3"
        / "ERGOAI_3.0"
    )
    vendor = distribution / "ErgoAI" / "runergo"
    xsb_configuration = "x86_64-unknown-linux-gnu"
    xsb = distribution / "XSB" / "config" / xsb_configuration / "bin" / "xsb"
    runtime_paths = vendor.parent / ".ergo_paths"
    java_settings = vendor.parent / "java" / "flora_settings.sh"
    config_file = vendor.parent / "ergoAI_config.sh"
    launcher = root / "bin" / "ergoai"
    xsb_user_aux = (
        root
        / "advisors"
        / "ergoai"
        / "3.0"
        / "runtime-state"
        / "xsb-user-aux"
    )
    release.parent.mkdir(parents=True)
    release.write_bytes(b"reviewed-release")
    _write_executable(vendor, "#!/bin/sh\nexit 0\n")
    xsb.parent.mkdir(parents=True, exist_ok=True)
    xsb.write_bytes(_minimal_elf(62))
    xsb.chmod(0o755)
    paths_source, java_source = advisors._ergoai_relocatable_runtime_sources(
        xsb_configuration
    )
    runtime_paths.write_bytes(paths_source)
    java_settings.parent.mkdir(parents=True)
    java_settings.write_bytes(java_source)
    config_file.write_bytes(b"fixture-hardened-ergoai-config\n")
    xsb_user_aux.mkdir(parents=True)
    runtime_library = distribution / "ErgoAI" / "lib" / "managed-runtime.xwam"
    runtime_library.parent.mkdir(parents=True)
    runtime_library.write_bytes(b"reviewed-runtime-library")
    _write_executable(launcher, _semantic_runner_source())
    for alias in ("runErgo.sh", "runergo"):
        _write_executable(root / "bin" / alias, launcher.read_text(encoding="utf-8"))

    release_digest = _digest(release)
    monkeypatch.setattr(advisors, "ERGOAI_RELEASE_SHA256", release_digest)
    monkeypatch.setattr(advisors, "ERGOAI_RELEASE_SIZE_BYTES", release.stat().st_size)
    monkeypatch.setattr(
        advisors,
        "ERGOAI_CONFIG_HARDENED_SHA256",
        _digest(config_file),
    )
    semantic_checks = advisors.run_ergoai_semantic_checks(
        launcher,
        timeout=1,
        include_extended=True,
        bound_timeout_seconds=0.05,
        max_output_bytes=256,
    )
    assert semantic_checks["passed"] is True
    dependency_identity = advisors._ergoai_build_dependency_identity()
    assert dependency_identity["satisfied"] is True
    optional_java_identity = advisors._ergoai_optional_java_dependency_identity()
    bound_runtime_environment = (
        advisors._materialize_ergoai_bound_runtime_toolchain(
            install_root=root,
            version="3.0",
            dependency_identity=dependency_identity,
            optional_java_identity=optional_java_identity,
        )
    )
    version_banner = advisors.read_ergoai_version_banner(str(launcher))
    assert version_banner == "ErgoAI 3.0"
    tree_integrity = advisors._ergoai_vendor_tree_integrity(
        distribution.parent
    )
    manifest = {
        "schema_version": "ergoai-managed-vendor-identity/v1",
        "tool_id": "ergoai",
        "version": "3.0",
        "selected_platform": "linux-x86_64",
        "release_tag": advisors.ERGOAI_RELEASE_TAG,
        "release_url": advisors.ERGOAI_RELEASE_URL,
        "release_artifact_path": str(release.relative_to(root)),
        "release_artifact_sha256": release_digest,
        "release_artifact_size_bytes": release.stat().st_size,
        "vendor_executable": str(vendor.relative_to(root)),
        "vendor_executable_sha256": _digest(vendor),
        "xsb_executable": str(xsb.relative_to(root)),
        "xsb_executable_sha256": _digest(xsb),
        "xsb_configuration": xsb_configuration,
        "xsb_elf_machine": "x86_64",
        "xsb_user_aux_dir": str(xsb_user_aux.relative_to(root)),
        "runtime_state_policy": (
            "mutable-nonauthoritative-outside-vendor-identity/v1"
        ),
        "runtime_workspace_cleanup_policy": (
            "normal-and-handled-signals-clean-sigkill-orphans-retained/v1"
        ),
        "runtime_execution_policy": (
            "private-ergoai-copy-shared-immutable-xsb/v1"
        ),
        "java_consumer_policy": "private-ergoai-copy-java-consumers/v2",
        "runtime_paths_file": str(runtime_paths.relative_to(root)),
        "runtime_paths_sha256": _digest(runtime_paths),
        "java_settings_file": str(java_settings.relative_to(root)),
        "java_settings_sha256": _digest(java_settings),
        "config_file": str(config_file.relative_to(root)),
        "config_file_sha256": _digest(config_file),
        "launcher": str(launcher.relative_to(root)),
        "launcher_sha256": _digest(launcher),
        "launcher_digests": {
            name: _digest(root / "bin" / name)
            for name in advisors.ERGOAI_EXECUTABLES
        },
        "version_banner_digest_sha256": hashlib.sha256(
            version_banner.encode("utf-8")
        ).hexdigest(),
        "semantic_checks": semantic_checks,
        "build_dependency_identity": dependency_identity,
        "optional_java_dependency_identity": optional_java_identity,
        "bound_runtime_environment": bound_runtime_environment,
        "bound_build_environment": {
            "schema_version": "ergoai-bound-build-environment/v1",
            "ambient_toolchain_overrides_inherited": False,
            "path_model": "private-staging-only/v1",
            "allowlisted_environment_keys": list(
                advisors.ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS
            ),
            "command_count": len(advisors.ERGOAI_BUILD_COMMANDS),
            "commands_digest_sha256": "0" * 64,
        },
        "config_hardening": {
            "schema_version": "ergoai-config-hardening/v1",
            "private_xsb_workspace_required": True,
            "exact_replacement_count": (
                advisors.ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT
            ),
            "source_sha256": advisors.ERGOAI_CONFIG_SOURCE_SHA256,
            "hardened_sha256": advisors.ERGOAI_CONFIG_HARDENED_SHA256,
        },
        "checksum_verified": True,
        "is_live_vendor": True,
        "is_hermetic_advisor_shim": False,
        "role": advisors.ADVISOR_ROLE,
        "authority_ceiling": advisors.ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "atomic_publish": True,
        "relocatable_install": True,
        "runtime_paths_relative": True,
        "relocation_certification_scope": (
            "executed-runtime-and-bundled-java-consumers/v1"
        ),
        "developer_rebuild_metadata_relocated": False,
        "vendor_tree_digest_sha256": tree_integrity["digest_sha256"],
        "vendor_tree_file_count": tree_integrity["file_count"],
        "vendor_tree_excluded_runtime_cache_count": tree_integrity[
            "excluded_runtime_cache_count"
        ],
        "vendor_tree_exclusion_policy": tree_integrity["exclusion_policy"],
        "install_publication_model": (
            "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
        ),
        "publication_commit_point": "atomic_identity_manifest_replace",
        "license": "Apache-2.0",
        "license_components": list(advisors.ERGOAI_LICENSE_COMPONENTS),
        "source": "https://github.com/ErgoAI/ErgoEngine",
    }
    manifest["identity_digest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identity_path = root / "advisors" / "ergoai" / "3.0" / "identity.json"
    identity_path.write_text(json.dumps(manifest), encoding="utf-8")

    bound = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert bound["managed_vendor_provenance_verified"] is True, {
        "reason_codes": bound.get("reason_codes"),
        "scalar_checks": bound.get("scalar_checks"),
        "path_checks": bound.get("path_checks"),
        "semantic_evidence_checks": bound.get("semantic_evidence_checks"),
    }
    assert bound["selected_executable_bound"] is True
    assert bound["version_match"] is True

    # Mutable cache contents are not managed identity. Clearing the cache is
    # valid, while redirecting its declared location through any symlinked path
    # component must fail closed.
    xsb_user_aux.rmdir()
    cache_cleared = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert cache_cleared["managed_vendor_provenance_verified"] is True
    external_runtime_state = tmp_path / "external-runtime-state"
    (external_runtime_state / "xsb-user-aux").mkdir(parents=True)
    runtime_state = xsb_user_aux.parent
    runtime_state.rmdir()
    runtime_state.symlink_to(external_runtime_state, target_is_directory=True)
    redirected_cache = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert redirected_cache["managed_vendor_provenance_verified"] is False
    assert "xsb_user_aux_directory_mismatch" in redirected_cache["reason_codes"]
    runtime_state.unlink()
    xsb_user_aux.mkdir(parents=True)

    wrapper = ErgoAIWrapper(
        binary=launcher,
        lazy_install=False,
        install_root=root,
        platform_key="linux-x86_64",
    )
    assert wrapper.is_live_vendor_execution() is True
    poison_bin = tmp_path / "wrapper-poison-path"
    poison_bin.mkdir()
    poison_marker = tmp_path / "wrapper-poison-command-ran"
    _write_executable(
        poison_bin / "dirname",
        "#!/bin/sh\n"
        f"printf poison > {str(poison_marker)!r}\n"
        "exit 97\n",
    )
    captured_runtime_path = tmp_path / "captured-managed-runtime-path"
    query = wrapper.query(
        "fvt_ergo_subject : fvt_ergo_expected",
        env={
            "PATH": str(poison_bin),
            "FVT_CAPTURE_RUNTIME_PATH": str(captured_runtime_path),
        },
    )
    assert query.status.value == "success"
    assert captured_runtime_path.read_text(encoding="utf-8") == str(
        root / "advisors" / "ergoai" / "3.0" / "runtime-toolchain-bin"
    )
    assert wrapper._last_execution_evidence["managed_runtime_path_bound"] is True
    assert not poison_marker.exists()

    stale_marker = tmp_path / "stale-launcher-was-executed"
    original_launcher_source = launcher.read_text(encoding="utf-8")
    _write_executable(
        launcher,
        f"#!/bin/sh\ntouch '{stale_marker}'\nprintf 'ErgoAI 3.0\\n'\n",
    )
    stale = wrapper.run_live_semantic_adapter(require_managed_vendor=True)
    assert stale["passed"] is False
    assert stale["live_vendor_execution"] is False
    assert "managed_vendor_provenance_unverified" in stale["block_reasons"]
    assert not stale_marker.exists()
    _write_executable(launcher, original_launcher_source)

    alias = root / "bin" / "runergo"
    alias_source = alias.read_bytes()
    alias.unlink()
    alias.symlink_to(launcher)
    symlink_alias = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert symlink_alias["managed_vendor_provenance_verified"] is False
    assert "launcher_runergo_digest_mismatch" in symlink_alias["reason_codes"]
    alias.unlink()
    alias.write_bytes(alias_source)
    alias.chmod(0o755)

    executed_marker = tmp_path / "foreign-was-executed"
    foreign = _write_executable(
        tmp_path / "foreign-ergoai",
        f"#!/bin/sh\ntouch '{executed_marker}'\nprintf 'ErgoAI 3.0\\n'\n",
    )
    rejected = advisors.probe_ergoai_identity(
        executable=str(foreign),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )

    assert rejected["managed_vendor_provenance_verified"] is False
    assert rejected["selected_executable_bound"] is False
    assert "selected_executable_not_bound_to_manifest" in rejected["reason_codes"]
    assert not executed_marker.exists()

    hidden_cache = distribution / "ErgoAI" / ".ergo_aux_files" / "escaping.fpj"
    hidden_cache.parent.mkdir(parents=True, exist_ok=True)
    hidden_cache.symlink_to("/etc/passwd")
    hidden_symlink = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert hidden_symlink["managed_vendor_provenance_verified"] is False
    assert "vendor_tree_digest_mismatch" in hidden_symlink["reason_codes"]
    hidden_cache.unlink()

    runtime_library.write_bytes(b"tampered-runtime-library")
    tampered_tree = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert tampered_tree["managed_vendor_provenance_verified"] is False
    assert "vendor_tree_digest_mismatch" in tampered_tree["reason_codes"]
    runtime_library.write_bytes(b"reviewed-runtime-library")

    # Even a locally recomputed manifest digest cannot bless changed runtime
    # configuration: provenance binds the exact reviewed relative source.
    runtime_paths.write_text(
        "FLORADIR=/tmp/foreign\nPROLOG=/tmp/foreign/xsb\n",
        encoding="utf-8",
    )
    manifest["runtime_paths_sha256"] = _digest(runtime_paths)
    manifest.pop("identity_digest_sha256", None)
    manifest["identity_digest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identity_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered_runtime = advisors.probe_ergoai_identity(
        executable=str(launcher),
        install_root=root,
        require_managed_vendor=True,
        platform_key="linux-x86_64",
    )
    assert tampered_runtime["managed_vendor_provenance_verified"] is False
    assert (
        "runtime_configuration_runtime_paths_exact_content_mismatch"
        in tampered_runtime["reason_codes"]
    )


def test_wrapper_distinguishes_external_from_managed_and_enforces_cap(
    tmp_path: Path,
) -> None:
    runner = _write_executable(
        tmp_path / "ergoai",
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdin.read()\n"
        "sys.stdout.write('X' * 1048576)\n"
        "sys.stdout.flush()\n"
        "time.sleep(5)\n",
    )
    wrapper = ErgoAIWrapper(binary=runner, lazy_install=False)

    assert wrapper.is_external_process_execution() is True
    assert wrapper.is_live_vendor_execution() is False
    result = wrapper.evaluate_bounded_goal(
        "fvt_subject : fvt_expected",
        timeout_seconds=2,
        max_output_bytes=129,
    )

    assert result["status"] == "resource_bound"
    assert result["resource_bound_enforced"] is True
    assert result["max_output_bytes"] == 129
    assert result["observed_output_bytes"] > 129
    assert result["external_process_execution"] is True
    assert result["managed_vendor_provenance_verified"] is False


def test_installer_declares_atomic_relocatable_publication() -> None:
    policy = advisors.plugin_manifest()["policy"]

    assert policy["ergoai_atomic_publish"] is True
    assert policy["ergoai_relocatable_install"] is True
    assert policy["ergoai_runtime_execution_policy"] == (
        "private-ergoai-copy-shared-immutable-xsb/v1"
    )
    assert policy["ergoai_java_consumer_policy"] == (
        "private-ergoai-copy-java-consumers/v2"
    )
    assert policy["ergoai_relocation_certification_scope"] == (
        "executed-runtime-and-bundled-java-consumers/v1"
    )
    assert policy["ergoai_developer_rebuild_metadata_relocated"] is False
    assert policy["ergoai_runtime_workspace_cleanup_policy"] == (
        "normal-and-handled-signals-clean-sigkill-orphans-retained/v1"
    )
    assert (
        policy["ergoai_publication_model"]
        == "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
    )


def test_force_quarantines_unverified_vendor_without_reblessing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(advisors, "_ergoai_missing_build_commands", lambda: [])
    monkeypatch.setattr(
        advisors,
        "_copy_or_download_ergoai_artifact",
        lambda pin, destination, **kwargs: (
            True,
            pin.sha256,
            pin.artifact_size_bytes,
        ),
    )
    repo_root = Path(__file__).resolve().parents[5]

    def vendor_path(root: Path) -> Path:
        return advisors._ergoai_vendor_root(
            root,
            advisors.ERGOAI_VERSION,
            advisors.ERGOAI_RELEASE_SHA256,
        )

    def ensure(root: Path, *, force: bool):
        return advisors.ensure_ergoai(
            yes=True,
            strict=False,
            force=force,
            install_root=root,
            repo_root=repo_root,
            platform_key="linux-aarch64",
            hermetic_shim=False,
            test_mode=True,
            artifact_path=tmp_path / "prefetched.run",
            install_timeout=1,
        )

    refused_root = tmp_path / "refused"
    refused_vendor = vendor_path(refused_root)
    refused_vendor.mkdir(parents=True)
    refused_marker = refused_vendor / "unverified-marker"
    refused_marker.write_text("preserve-me\n", encoding="utf-8")
    refused = ensure(refused_root, force=False)
    assert "unverified_preexisting_vendor_tree" in refused.reason_codes
    assert refused_marker.read_text(encoding="utf-8") == "preserve-me\n"

    recovered = ensure(refused_root, force=True)
    assert "unverified_preexisting_vendor_tree" not in recovered.reason_codes
    quarantined_relative = recovered.bindings["quarantined_unverified_vendor_tree"]
    quarantined = refused_root / quarantined_relative
    assert quarantined.parent == (
        refused_root / "advisors" / "ergoai" / "3.0" / "quarantine"
    )
    assert (quarantined / refused_marker.name).read_text(encoding="utf-8") == (
        "preserve-me\n"
    )
    assert recovered.bindings["quarantine_never_reblessed"] is True
    assert not refused_vendor.exists()

    symlink_root = tmp_path / "symlink-vendor"
    external_vendor = tmp_path / "external-vendor"
    external_vendor.mkdir()
    (external_vendor / "sentinel").write_text("external\n", encoding="utf-8")
    unsafe_vendor = vendor_path(symlink_root)
    unsafe_vendor.parent.mkdir(parents=True)
    unsafe_vendor.symlink_to(external_vendor, target_is_directory=True)
    unsafe = ensure(symlink_root, force=True)
    quarantined_link = (
        symlink_root / unsafe.bindings["quarantined_unverified_vendor_tree"]
    )
    assert quarantined_link.is_symlink()
    assert quarantined_link.resolve() == external_vendor.resolve()
    assert not os.path.lexists(unsafe_vendor)
    assert (external_vendor / "sentinel").read_text(encoding="utf-8") == (
        "external\n"
    )

    quarantine_root = tmp_path / "symlink-quarantine"
    quarantine_vendor = vendor_path(quarantine_root)
    quarantine_vendor.mkdir(parents=True)
    (quarantine_vendor / "orphan").write_text("orphan\n", encoding="utf-8")
    external_quarantine = tmp_path / "external-quarantine"
    external_quarantine.mkdir()
    quarantine_link = quarantine_vendor.parent / "quarantine"
    quarantine_link.symlink_to(external_quarantine, target_is_directory=True)
    unsafe_quarantine = ensure(quarantine_root, force=True)
    assert "unsafe_quarantine_directory" in unsafe_quarantine.reason_codes
    assert (quarantine_vendor / "orphan").read_text(encoding="utf-8") == (
        "orphan\n"
    )


def test_wrapper_install_root_does_not_fall_back_to_global_binary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_binary = _write_executable(
        tmp_path / "global" / "ergoai",
        "#!/bin/sh\nprintf 'ErgoAI 3.0\\n'\n",
    )
    monkeypatch.setenv("ERGOAI_BINARY", str(global_binary))

    wrapper = ErgoAIWrapper(
        install_root=tmp_path / "empty-managed-root",
        lazy_install=False,
    )

    assert wrapper.binary is None
    assert wrapper.simulation_mode is True
    assert wrapper.is_live_vendor_execution() is False


def test_managed_launcher_and_runtime_configuration_survive_root_move(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original-root"
    vendor_root = advisors._ergoai_vendor_root(
        original,
        advisors.ERGOAI_VERSION,
        advisors.ERGOAI_RELEASE_SHA256,
    )
    distribution = vendor_root / "ERGOAI_3.0"
    ergo_root = distribution / "ErgoAI"
    runergo = _write_executable(
        ergo_root / "runergo",
        "#!/bin/sh\n"
        "set -eu\n"
        "thisdir=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        ". \"$thisdir/.ergo_paths\"\n"
        "printf '%s\\n%s\\n' \"$FLORADIR\" \"$PROLOG\"\n",
    )
    (ergo_root / ".ergo_paths").write_text(
        f"FLORADIR=\"'{ergo_root}'\"\nPROLOG=\"{distribution}/XSB/bin/xsb\"\n",
        encoding="utf-8",
    )
    java_settings = ergo_root / "java" / "flora_settings.sh"
    java_settings.parent.mkdir(parents=True)
    java_settings.write_text(
        f"FLORADIR={ergo_root}\nPROLOGDIR={distribution}/XSB/config/test/bin\n",
        encoding="utf-8",
    )
    java_cache = (
        ergo_root
        / "java"
        / "API"
        / "examples"
        / "generated"
        / ".ergo_aux_files"
        / "runtime.fdb"
    )
    java_cache.parent.mkdir(parents=True)
    java_cache.write_text("stable-precompiled-cache\n", encoding="utf-8")
    java_consumer = _write_executable(
        ergo_root / "java" / "API" / "examples" / "runExample.sh",
        "#!/bin/sh\n"
        ". ../../flora_settings.sh\n"
        "mkdir -p generated/.ergo_aux_files\n"
        "printf 'runtime-mutated-cache\\n' > "
        "generated/.ergo_aux_files/runtime.fdb\n"
        "touch generated/.ergo_aux_files/runtime.fpj\n"
        "printf '%s\\n%s\\n' \"$FLORADIR\" \"$PROLOGDIR\"\n"
        "java --managed-runtime-path-probe\n",
    )
    java_builder = _write_executable(
        ergo_root / "java" / "API" / "build.sh",
        "#!/bin/sh\n"
        ". ../flora_settings.sh\n"
        "printf 'managed-java-build-output\\n' > ../built.jar\n",
    )
    xsb = _write_executable(
        distribution / "XSB" / "config" / "test" / "bin" / "xsb",
        "#!/bin/sh\nexit 0\n",
    )
    _write_executable(
        distribution / "XSB" / "bin" / "xsb",
        "#!/bin/sh\nexit 0\n",
    )
    absolute_link = distribution / "XSB" / "emu" / "runtime.o"
    absolute_link.parent.mkdir(parents=True)
    absolute_link.symlink_to(
        tmp_path / "XSB-build" / "config" / "test" / "bin" / "xsb"
    )

    advisors._make_ergoai_tree_relocatable(
        vendor_root,
        version="3.0",
        xsb_configuration="test",
    )
    dependency_identity = advisors._ergoai_build_dependency_identity()
    optional_java_identity = advisors._ergoai_optional_java_dependency_identity()
    fake_java_bin = tmp_path / "reviewed-java-bin"
    fake_java_bin.mkdir()
    _write_executable(
        fake_java_bin / "java",
        "#!/bin/sh\nprintf 'bound-java\\n'\n",
    )
    for name in ("javac", "jar"):
        _write_executable(fake_java_bin / name, "#!/bin/sh\nexit 0\n")
    for name in ("java", "javac", "jar"):
        command = fake_java_bin / name
        optional_java_identity["commands"][name] = {
            "present": True,
            "resolved_path": str(command.resolve()),
            "executable_sha256": _digest(command),
        }
    optional_java_identity["commands"]["java"].update(
        {
            "minimum_version": ">=1.8",
            "observed_version": "17.0",
            "version_satisfied": True,
            "version_banner_digest_sha256": "0" * 64,
        }
    )
    optional_java_identity["missing_commands"] = []
    optional_java_identity["version_mismatches"] = []
    optional_java_identity["satisfied"] = True
    advisors._materialize_ergoai_bound_runtime_toolchain(
        install_root=original,
        version="3.0",
        dependency_identity=dependency_identity,
        optional_java_identity=optional_java_identity,
    )
    advisors._write_vendor_ergoai_launchers(
        install_root=original,
        vendor_binary=runergo,
        version="3.0",
        platform_key="linux-x86_64",
    )

    moved = tmp_path / "moved-root"
    original.rename(moved)
    moved_distribution = moved / distribution.relative_to(original)
    poison_path_sentinel = tmp_path / "poison-path-used"
    poison_bin = tmp_path / "poison-bin"
    poison_bin.mkdir()
    for name in (
        "dirname",
        "mkdir",
        "mktemp",
        "cp",
        "ln",
        "rm",
        "touch",
        "java",
        "javac",
        "jar",
    ):
        _write_executable(
            poison_bin / name,
            "#!/bin/sh\n"
            f"printf '%s\\n' {name!r} >> {str(poison_path_sentinel)!r}\n"
            "exit 97\n",
        )
    poisoned_runtime_env = dict(os.environ)
    poisoned_runtime_env["PATH"] = str(poison_bin)
    vendor_integrity_before = advisors._ergoai_vendor_tree_integrity(
        moved_distribution.parent
    )
    completed = subprocess.run(
        [moved / "bin" / "ergoai"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=poisoned_runtime_env,
    )

    assert completed.returncode == 0
    assert str(original) not in completed.stdout
    main_paths = completed.stdout.splitlines()
    assert len(main_paths) == 2
    main_flora = Path(main_paths[0].strip("'"))
    main_prolog = Path(main_paths[1])
    main_workspace = main_flora.parents[1]
    assert main_workspace.parent == (
        moved
        / "advisors"
        / "ergoai"
        / "3.0"
        / "runtime-state"
        / "runtime-workspaces"
    )
    assert main_workspace.name.startswith("run.")
    assert main_flora.relative_to(main_workspace) == Path("ERGOAI_3.0/ErgoAI")
    assert main_prolog.relative_to(main_workspace) == Path(
        "ERGOAI_3.0/XSB/config/test/bin/xsb"
    )
    assert not main_workspace.exists()
    assert (moved / xsb.relative_to(original)).is_file()
    moved_link = moved / absolute_link.relative_to(original)
    assert moved_link.is_symlink()
    assert not Path(os.readlink(moved_link)).is_absolute()
    assert moved_link.resolve() == (moved / xsb.relative_to(original)).resolve()
    moved_java_settings = moved / java_settings.relative_to(original)
    java_env = dict(poisoned_runtime_env)
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    poisoned_home = tmp_path / "poisoned-ergoai-home"
    poisoned_home.mkdir()
    poison_sentinel = poisoned_home / "must-not-be-touched"
    poison_sentinel.write_text("external\n", encoding="utf-8")
    java_env["HOME"] = str(empty_home)
    java_env["TMPDIR"] = str(tmp_path / "nonexistent-ambient-tmp")
    java_env["ERGOAI_HOME"] = str(poisoned_home)
    java_env["XSB_USER_AUXDIR"] = str(tmp_path / "poisoned-xsb-aux")
    java_probe = subprocess.run(
        [
            "/bin/bash",
            "-c",
            '. "$1"; printf "%s\\n%s\\n" "$FLORADIR" "$PROLOGDIR"',
            "/bin/bash",
            str(moved_java_settings),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=java_env,
    )
    assert java_probe.returncode == 0
    assert java_probe.stdout.splitlines() == [
        str(moved_distribution / "ErgoAI"),
        str(moved_distribution / "XSB" / "config" / "test" / "bin"),
    ]
    moved_java_consumer = moved / java_consumer.relative_to(original)
    posix_probe = subprocess.run(
        ["/bin/sh", f"./{moved_java_consumer.name}"],
        cwd=moved_java_consumer.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=java_env,
    )
    assert posix_probe.returncode == 0
    java_paths = [Path(item) for item in posix_probe.stdout.splitlines()]
    assert len(java_paths) == 3
    java_workspace = java_paths[0].parents[1]
    assert java_workspace.parent == (
        moved
        / "advisors"
        / "ergoai"
        / "3.0"
        / "runtime-state"
        / "java-workspaces"
    )
    assert java_workspace.name.startswith("run.")
    assert java_paths[0].relative_to(java_workspace) == Path(
        "ERGOAI_3.0/ErgoAI"
    )
    assert java_paths[1].relative_to(java_workspace) == Path(
        "ERGOAI_3.0/XSB/config/test/bin"
    )
    assert posix_probe.stdout.splitlines()[2] == "bound-java"
    assert not java_workspace.exists()

    build_output_root = tmp_path / "java-build-outputs"
    build_env = dict(java_env)
    build_env["ERGOAI_JAVA_OUTPUT_DIR"] = str(build_output_root)
    moved_java_builder = moved / java_builder.relative_to(original)
    build_probe = subprocess.run(
        ["/bin/sh", f"./{moved_java_builder.name}"],
        cwd=moved_java_builder.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=build_env,
    )
    assert build_probe.returncode == 0
    output_prefix = "Managed ErgoAI Java build outputs: "
    output_line = next(
        line for line in build_probe.stderr.splitlines() if line.startswith(output_prefix)
    )
    build_output = Path(output_line.removeprefix(output_prefix))
    assert build_output.parent == build_output_root
    assert build_output.name.startswith("API-build.complete.")
    assert (build_output / "built.jar").read_text(encoding="utf-8") == (
        "managed-java-build-output\n"
    )
    assert not (moved_distribution / "ErgoAI" / "java" / "built.jar").exists()
    assert not list(moved_distribution.rglob("*.fpj"))
    moved_java_cache = moved / java_cache.relative_to(original)
    assert moved_java_cache.read_text(encoding="utf-8") == (
        "stable-precompiled-cache\n"
    )
    assert poison_sentinel.read_text(encoding="utf-8") == "external\n"
    assert not poison_path_sentinel.exists()
    java_workspaces = (
        moved / "advisors" / "ergoai" / "3.0" / "runtime-state" / "java-workspaces"
    )
    assert not list(java_workspaces.glob("run.*"))
    assert not list(moved.rglob("*.partial"))
    assert advisors._ergoai_vendor_tree_integrity(moved_distribution.parent) == (
        vendor_integrity_before
    )

    runtime_state = moved / "advisors" / "ergoai" / "3.0" / "runtime-state"
    runtime_workspaces = runtime_state / "runtime-workspaces"
    runtime_workspaces.rmdir()
    java_workspaces.rmdir()
    runtime_state.rmdir()
    external_runtime_state = tmp_path / "external-runtime-poison"
    external_runtime_state.mkdir()
    external_sentinel = external_runtime_state / "must-survive"
    external_sentinel.write_text("external-runtime\n", encoding="utf-8")
    runtime_state.symlink_to(external_runtime_state, target_is_directory=True)
    blocked_main = subprocess.run(
        [moved / "bin" / "ergoai"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    blocked_java = subprocess.run(
        ["/bin/sh", f"./{moved_java_consumer.name}"],
        cwd=moved_java_consumer.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=java_env,
    )
    assert blocked_main.returncode != 0
    assert blocked_java.returncode != 0
    assert external_sentinel.read_text(encoding="utf-8") == "external-runtime\n"

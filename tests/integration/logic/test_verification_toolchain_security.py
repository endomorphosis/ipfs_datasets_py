"""Security and isolation tests for verification toolchain hardening (LFV-G082).

Covers:

* explicit pinned tool discovery/install metadata for every provider;
* declared gaps for TLC, Hyper tools, Datalog/SecPAL external engines, and
  runtime-MTL external monitors;
* install consent, checksum, and no-import-side-effect gates;
* JVM/opam/Maude/circuit dependency bindings;
* adversarial path traversal, oversized output, process-tree cleanup, and
  secret/witness redaction through the shared bounded lifecycle.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends import toolchains
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    ProcessInvocation,
    RawProcessResult,
    ToolProcessError,
    ToolRunLimits,
    ToolRunRequest,
)
from ipfs_datasets_py.logic.backends.toolchains import (
    VERIFICATION_TOOLCHAIN_REGISTRY_VERSION,
    DependencyKind,
    InstallAvailability,
    InstallGapKind,
    IsolationMode,
    ToolchainError,
    VerificationToolchainRegistry,
    authorize_provider_install,
    bound_dependency_kinds,
    default_registry,
    get_toolchain,
    install_is_forbidden_on_import,
    list_declared_install_gaps,
    list_toolchains,
    managed_pin_versions,
    registry_side_effect_free_on_import,
    reset_default_registry,
    resource_class_for,
    secret_handling_policy,
    witness_handling_policy,
)
from ipfs_datasets_py.logic.external_provers import lazy_installer
from ipfs_datasets_py.logic.integration.bridges import prover_installer

PYTHON = sys.executable


@pytest.fixture(autouse=True)
def _reset_toolchain_registry() -> None:
    reset_default_registry()
    yield
    reset_default_registry()


# ---------------------------------------------------------------------------
# Registry metadata and declared gaps
# ---------------------------------------------------------------------------


def test_registry_interface_and_import_are_side_effect_free() -> None:
    assert VERIFICATION_TOOLCHAIN_REGISTRY_VERSION == "VerificationToolchainRegistry@1"
    assert registry_side_effect_free_on_import() is True
    assert install_is_forbidden_on_import() is True
    assert lazy_installer.import_time_install_forbidden() is True


def test_default_registry_lists_every_provider_with_resource_class() -> None:
    registry = default_registry()
    assert isinstance(registry, VerificationToolchainRegistry)
    provider_ids = set(registry.list_provider_ids())
    required = {
        "z3",
        "cvc5",
        "vampire",
        "eprover",
        "apalache",
        "tlc",
        "tamarin",
        "maude",
        "proverif",
        "lean",
        "coq",
        "isabelle",
        "hyperltl",
        "autohyper",
        "mchyper",
        "datalog-authorization",
        "secpal-authorization",
        "souffle",
        "secpal",
        "runtime-mtl",
        "runtime-mtl-external",
        "java",
        "opam",
        "zkp-circuit",
    }
    assert required.issubset(provider_ids)
    for provider_id in required:
        descriptor = get_toolchain(provider_id)
        assert descriptor.resource_class
        assert descriptor.isolation.private_workspace is True
        assert IsolationMode.PATH_CONTAINMENT in descriptor.isolation.modes
        assert IsolationMode.SECRET_REDACTION in descriptor.isolation.modes
        payload = descriptor.to_dict()
        assert payload["provider_id"] == provider_id
        assert payload["schema_version"]


def test_required_install_gaps_are_declared() -> None:
    gaps = {gap.gap_id for gap in list_declared_install_gaps()}
    assert InstallGapKind.TLC not in gaps
    assert InstallGapKind.HYPER_TOOLS in gaps
    assert InstallGapKind.DATALOG_SECPAL_EXTERNAL in gaps
    assert InstallGapKind.RUNTIME_MTL_EXTERNAL in gaps

    registry = default_registry()
    registry.assert_required_gaps_declared()
    tlc = get_toolchain("tlc")
    assert tlc.availability is InstallAvailability.MANAGED_PIN
    assert tlc.installer_entry == "ensure_tlc"
    assert len(tlc.pins) == 1
    assert tlc.pins[0].version == "1.8.0"
    assert (
        tlc.pins[0].sha256
        == "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5"
    )
    assert get_toolchain("hyperltl").availability is InstallAvailability.DECLARED_GAP
    assert get_toolchain("autohyper").availability is InstallAvailability.DECLARED_GAP
    assert get_toolchain("mchyper").availability is InstallAvailability.DECLARED_GAP
    assert get_toolchain("souffle").availability is InstallAvailability.DECLARED_GAP
    assert get_toolchain("secpal").availability is InstallAvailability.DECLARED_GAP
    assert (
        get_toolchain("runtime-mtl-external").availability
        is InstallAvailability.DECLARED_GAP
    )
    # In-process engines remain available without install.
    assert (
        get_toolchain("datalog-authorization").availability
        is InstallAvailability.IN_PROCESS
    )
    assert (
        get_toolchain("runtime-mtl").availability is InstallAvailability.IN_PROCESS
    )


def test_jvm_opam_maude_and_circuit_dependencies_are_bound() -> None:
    registry = default_registry()
    registry.assert_runtime_dependencies_bound()
    bound = bound_dependency_kinds()
    assert "apalache" in bound[DependencyKind.JVM.value]
    assert "tlc" in bound[DependencyKind.JVM.value]
    assert "coq" in bound[DependencyKind.OPAM.value]
    assert "proverif" in bound[DependencyKind.OPAM.value]
    assert "tamarin" in bound[DependencyKind.MAUDE.value]
    assert "zkp-circuit" in bound[DependencyKind.CIRCUIT.value]
    # Companion carriers are registered.
    assert get_toolchain("java").runtime.value == "jvm"
    assert get_toolchain("opam").pins[0].version
    assert get_toolchain("maude").availability is InstallAvailability.MANAGED_PIN


def test_managed_pins_require_version_metadata_and_match_installer_inventory() -> None:
    versions = managed_pin_versions()
    assert versions["apalache"] == prover_installer.APALACHE_VERSION
    assert versions["cvc5"] == prover_installer.CVC5_VERSION
    assert versions["tamarin"] == prover_installer.TAMARIN_VERSION
    assert versions["maude"] == prover_installer.MAUDE_VERSION
    assert versions["proverif"] == prover_installer.PROVERIF_VERSION
    inventory = prover_installer.pinned_release_inventory()
    assert inventory["apalache"]["sha256"] == prover_installer.APALACHE_PORTABLE_SHA256
    assert inventory["proverif"]["sha256"] == prover_installer.PROVERIF_SOURCE_SHA256
    apalache = get_toolchain("apalache")
    assert apalache.pins[0].is_checksummed
    assert apalache.pins[0].sha256 == prover_installer.APALACHE_PORTABLE_SHA256


# ---------------------------------------------------------------------------
# Install consent and gap refusal
# ---------------------------------------------------------------------------


def test_install_requires_explicit_call_and_yes_consent() -> None:
    with pytest.raises(ToolchainError, match="explicit"):
        authorize_provider_install("apalache", yes=True, explicit_call=False)
    with pytest.raises(ToolchainError, match="yes=True"):
        authorize_provider_install("apalache", yes=False, explicit_call=True)
    with pytest.raises(ToolchainError, match="import"):
        authorize_provider_install(
            "apalache", yes=True, explicit_call=True, import_context=True
        )
    with pytest.raises(ToolchainError, match="capability discovery"):
        authorize_provider_install(
            "apalache", yes=True, explicit_call=True, capability_discovery=True
        )
    # Happy path does not raise.
    authorize_provider_install("apalache", yes=True, explicit_call=True)


def test_declared_gap_and_in_process_providers_refuse_managed_install() -> None:
    for provider in ("hyperltl", "souffle", "runtime-mtl-external"):
        with pytest.raises(ToolchainError, match="declared install gap"):
            authorize_provider_install(provider, yes=True, explicit_call=True)
    authorize_provider_install(
        "tlc",
        yes=True,
        explicit_call=True,
        checksum_verified=True,
    )
    with pytest.raises(ToolchainError, match="in-process"):
        authorize_provider_install(
            "datalog-authorization", yes=True, explicit_call=True
        )


def test_managed_install_requires_checksum_verification_when_flagged() -> None:
    with pytest.raises(ToolchainError, match="checksum"):
        authorize_provider_install(
            "apalache",
            yes=True,
            explicit_call=True,
            checksum_verified=False,
        )
    authorize_provider_install(
        "apalache",
        yes=True,
        explicit_call=True,
        checksum_verified=True,
    )


def test_prover_installer_requires_explicit_consent_and_blocks_test_package_mutation() -> None:
    with pytest.raises(PermissionError, match="yes=True"):
        prover_installer.require_explicit_install_consent(yes=False)
    prover_installer.require_explicit_install_consent(yes=True)
    with pytest.raises(PermissionError, match="system package"):
        prover_installer.refuse_system_package_mutation_in_tests(
            test_mode=True,
            system_package_mutation=True,
        )
    # Non-test contexts may still plan system packages (actual install is gated).
    prover_installer.refuse_system_package_mutation_in_tests(
        test_mode=False,
        system_package_mutation=True,
    )


def test_ensure_apalache_without_yes_does_not_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prover_installer, "_which", lambda *_a, **_k: None)
    called = {"download": False}

    def boom(*_a, **_k):
        called["download"] = True
        raise AssertionError("download must not run without yes=True")

    monkeypatch.setattr(prover_installer, "_download_release_artifact", boom)
    assert prover_installer.ensure_apalache(yes=False, strict=False) is False
    assert called["download"] is False


def test_lazy_installer_refuses_declared_gap_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "1")
    lazy_installer.reset_lazy_install_attempts()
    events: list[str] = []

    def progress(event: lazy_installer.ProverInstallEvent) -> None:
        events.append(event.phase)

    assert lazy_installer.lazy_install_prover("hyperltl", progress=progress) is False
    assert "blocked" in events
    assert "hyperltl" in lazy_installer.declared_install_gap_providers()


def test_lazy_install_disabled_by_default_and_import_context_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS", raising=False)
    assert lazy_installer.lazy_installs_enabled() is False
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_IMPORT_CONTEXT", "1")
    lazy_installer.reset_lazy_install_attempts()
    assert lazy_installer.lazy_install_prover("z3") is False


# ---------------------------------------------------------------------------
# Checksums and archive path containment
# ---------------------------------------------------------------------------


def test_verify_artifact_sha256_accepts_match_and_rejects_mismatch(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "tool.bin"
    payload = b"pinned-tool-bytes"
    artifact.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert prover_installer.verify_artifact_sha256(artifact, digest) == digest
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        prover_installer.verify_artifact_sha256(artifact, "0" * 64)


def test_safe_extract_tar_and_zip_reject_path_traversal(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    destination.mkdir()

    tar_path = tmp_path / "evil.tar"
    with tarfile.open(tar_path, "w") as bundle:
        info = tarfile.TarInfo(name="../escape.txt")
        data = b"pwn"
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        prover_installer.safe_extract_tar(tar_path, destination)

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as bundle:
        bundle.writestr("../escape.txt", "pwn")
    with pytest.raises(RuntimeError, match="unsafe archive member"):
        prover_installer.safe_extract_zip(zip_path, destination)

    # Safe members extract successfully.
    safe_tar = tmp_path / "safe.tar"
    with tarfile.open(safe_tar, "w") as bundle:
        info = tarfile.TarInfo(name="nested/tool.bin")
        data = b"ok"
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    safe_dest = tmp_path / "safe-out"
    prover_installer.safe_extract_tar(safe_tar, safe_dest)
    assert (safe_dest / "nested" / "tool.bin").read_bytes() == b"ok"


# ---------------------------------------------------------------------------
# Process isolation, secrets, and adversarial containment
# ---------------------------------------------------------------------------


def _runner(tmp_path: Path, executor=None) -> BoundedToolRunner:
    return BoundedToolRunner(
        executor=executor,
        workspace_root=tmp_path / "runs",
        base_environment={"PATH": os.environ.get("PATH", os.defpath)},
    )


def test_toolchain_isolation_policy_matches_bounded_runner_defaults() -> None:
    policy = get_toolchain("cvc5").isolation
    assert policy.shell_disabled is True
    assert policy.process_group_termination is True
    assert policy.path_traversal_rejected is True
    assert policy.secret_redaction is True
    assert policy.witness_redaction is True
    assert resource_class_for("cvc5").value == "solver"
    secrets = secret_handling_policy("cvc5")
    assert secrets.redact_argv and secrets.redact_stdout and secrets.forbid_secret_cache_keys
    witnesses = witness_handling_policy("zkp-circuit")
    assert witnesses.allow_private_witness_in_logs is False
    assert witnesses.redacted_public_references_only is True


@pytest.mark.parametrize(
    "path",
    ["../escape", "/absolute", "nested/../../escape", r"windows\\escape"],
)
def test_malicious_workspace_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(ToolProcessError):
        _runner(tmp_path).run(
            ToolRunRequest(argv=("fake",), input_files={path: "x"})
        )


def test_shell_metacharacters_are_literal_and_do_not_escape_workspace(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "must-not-exist"
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                "import sys; print(sys.argv[1])",
                f"; touch {marker}",
            )
        )
    )
    assert result.ok
    assert result.stdout.strip() == f"; touch {marker}"
    assert not marker.exists()


def test_secret_and_witness_material_is_redacted_from_results(
    tmp_path: Path,
) -> None:
    secret = "super-private-token"
    witness = "private-witness-material-xyz"

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        assert invocation.environment["API_TOKEN"] == secret
        (invocation.cwd / "witness.bin").write_text(
            f"witness={witness}; secret={secret}",
            encoding="utf-8",
        )
        return RawProcessResult(
            returncode=2,
            stdout=f"received {secret} and {witness}",
            stderr=f"failed with {secret}",
            error=f"tool rejected {secret}",
        )

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake", "--token", secret, f"--password={secret}"),
            environment={"API_TOKEN": secret},
            output_paths=("witness.bin",),
            secrets=(witness,),
        )
    )
    serialized = repr(result.to_dict())
    assert secret not in serialized
    assert witness not in serialized
    assert result.command == (
        "fake",
        "--token",
        "<redacted>",
        "--password=<redacted>",
    )
    assert "<redacted>" in result.stdout
    assert secret not in result.stdout
    assert witness not in result.stdout
    assert secret not in result.output_files["witness.bin"].decode("utf-8", "replace")
    assert witness not in result.output_files["witness.bin"].decode("utf-8", "replace")


def test_oversized_output_is_truncated_without_deadlock(tmp_path: Path) -> None:
    limits = ToolRunLimits(
        timeout_seconds=3,
        max_output_bytes=32,
        max_input_bytes=128,
        max_workspace_bytes=1024,
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                (
                    "import pathlib,sys;"
                    "sys.stdout.write('o'*100000);"
                    "sys.stderr.write('e'*100000);"
                    "pathlib.Path('large.txt').write_bytes(b'x'*100)"
                ),
            ),
            limits=limits,
            output_paths=("large.txt",),
        )
    )
    assert result.returncode == 0
    assert len(result.stdout.encode()) == 32
    assert len(result.stderr.encode()) == 32
    assert result.output_files["large.txt"] == b"x" * 32
    assert result.output_truncated


def test_timeout_terminates_process_tree(tmp_path: Path) -> None:
    limits = ToolRunLimits(
        timeout_seconds=0.15,
        termination_grace_seconds=0.1,
        max_output_bytes=128,
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(PYTHON, "-c", "import time; time.sleep(60)"),
            limits=limits,
        )
    )
    assert result.timed_out
    assert result.termination_reason == "timeout"
    assert result.process_tree_terminated
    assert result.returncode is not None


@pytest.mark.skipif(os.name != "posix", reason="process-group assertion is POSIX")
def test_timeout_terminates_descendant_process_tree(tmp_path: Path) -> None:
    code = (
        "import signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(60)']);"
        "print(p.pid,flush=True);time.sleep(60)"
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(PYTHON, "-c", code),
            limits=ToolRunLimits(
                timeout_seconds=0.2,
                termination_grace_seconds=0.05,
                max_output_bytes=128,
            ),
        )
    )
    child_pid = int(result.stdout.strip())
    deadline_alive = False
    try:
        os.kill(child_pid, 0)
        process_stat = Path(f"/proc/{child_pid}/stat")
        if process_stat.exists():
            # Zombie or missing means the tree was reaped.
            deadline_alive = ") Z " not in process_stat.read_text()
            # Give a short grace for reaping.
            import time

            for _ in range(50):
                try:
                    os.kill(child_pid, 0)
                    if process_stat.exists() and ") Z " in process_stat.read_text():
                        deadline_alive = False
                        break
                except ProcessLookupError:
                    deadline_alive = False
                    break
                time.sleep(0.02)
            else:
                try:
                    os.kill(child_pid, 0)
                    deadline_alive = True
                except ProcessLookupError:
                    deadline_alive = False
    except ProcessLookupError:
        deadline_alive = False
    assert result.timed_out
    assert result.process_tree_terminated
    assert deadline_alive is False


def test_environment_does_not_inherit_parent_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNRELATED_PARENT_SECRET", "do-not-inherit")
    captured: dict[str, str] = {}

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        captured.update(invocation.environment)
        return RawProcessResult(returncode=0, stdout=b"ok")

    _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake",),
            environment={"HOME": "/outside", "SAFE_SETTING": "yes"},
        )
    )
    assert "UNRELATED_PARENT_SECRET" not in captured
    assert captured["SAFE_SETTING"] == "yes"
    assert captured["HOME"] != "/outside"


def test_registry_to_dict_is_json_friendly_and_complete() -> None:
    payload = default_registry().to_dict()
    assert payload["interface_version"] == VERIFICATION_TOOLCHAIN_REGISTRY_VERSION
    assert payload["install_policy"]["never_on_import"] is True
    assert payload["install_policy"]["requires_explicit_yes"] is True
    assert payload["install_policy"]["forbid_system_package_mutation_in_tests"] is True
    gap_ids = {item["gap_id"] for item in payload["declared_gaps"]}
    assert {
        "hyper_tools",
        "datalog_secpal_external",
        "runtime_mtl_external",
    } <= gap_ids
    assert "tlc" not in gap_ids
    assert len(payload["providers"]) == len(list_toolchains())


def test_unknown_provider_fails_closed() -> None:
    with pytest.raises(ToolchainError, match="unknown provider"):
        get_toolchain("not-a-real-provider")


def test_install_policy_is_fail_closed() -> None:
    with pytest.raises(ToolchainError):
        toolchains.InstallPolicy(never_on_import=False)
    with pytest.raises(ToolchainError):
        toolchains.WitnessHandlingPolicy(allow_private_witness_in_logs=True)

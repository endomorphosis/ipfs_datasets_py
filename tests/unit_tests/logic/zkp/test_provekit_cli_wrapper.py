import os
import subprocess

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError
from ipfs_datasets_py.logic.zkp.provekit.cli import (
    ProveKitCLI,
    ProveKitCommand,
    SENSITIVE_REDACTION,
    discover_provekit_binary,
)


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_discovers_binary_from_explicit_environment(monkeypatch, tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    monkeypatch.setenv("IPFS_DATASETS_PROVEKIT_CLI", str(binary))

    assert discover_provekit_binary(search_path=False) == binary


def test_discovers_binary_from_package_candidate(tmp_path):
    binary = _executable(tmp_path / "bin" / "provekit-cli")

    assert (
        discover_provekit_binary(env={}, package_dir=tmp_path, search_path=False)
        == binary
    )


def test_invalid_explicit_environment_path_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("IPFS_DATASETS_PROVEKIT_CLI", str(tmp_path / "missing"))

    with pytest.raises(ZKPError, match="not executable"):
        discover_provekit_binary(search_path=False)


def test_build_prepare_command_uses_explicit_artifact_paths(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    cli = ProveKitCLI(binary_path=binary)

    command = cli.build_prepare_command(
        program_dir=tmp_path / "circuit",
        package="logic",
        target_dir=tmp_path / "target",
        prover_key_path=tmp_path / "keys" / "logic.pkp",
        verifier_key_path=tmp_path / "keys" / "logic.pkv",
        force=True,
    )

    assert command.argv == (
        str(binary),
        "prepare",
        "--package",
        "logic",
        "--target-dir",
        str(tmp_path / "target"),
        "--force",
        "--pkp",
        str(tmp_path / "keys" / "logic.pkp"),
        "--pkv",
        str(tmp_path / "keys" / "logic.pkv"),
        str(tmp_path / "circuit"),
    )


def test_build_prove_command_marks_witness_input_path_sensitive(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    cli = ProveKitCLI(binary_path=binary)
    private_input = tmp_path / "private" / "Prover.toml"

    command = cli.build_prove_command(
        prover_key_path=tmp_path / "logic.pkp",
        input_path=private_input,
        proof_path=tmp_path / "proof.np",
    )

    assert str(private_input) in command.argv
    assert str(private_input) not in " ".join(command.redacted_argv())
    assert SENSITIVE_REDACTION in " ".join(command.redacted_argv())


def test_build_verify_command_uses_verifier_and_proof_paths(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    cli = ProveKitCLI(binary_path=binary)

    command = cli.build_verify_command(
        verifier_key_path=tmp_path / "logic.pkv",
        proof_path=tmp_path / "proof.np",
    )

    assert command.argv == (
        str(binary),
        "verify",
        "--verifier",
        str(tmp_path / "logic.pkv"),
        "--proof",
        str(tmp_path / "proof.np"),
    )


def test_run_command_passes_actual_argv_but_redacts_result(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    private_input = str(tmp_path / "private" / "Prover.toml")
    private_axiom = "secret_axiom(alpha)"
    captured = {}

    def fake_runner(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"loaded {private_input}; witness {private_axiom}",
            stderr="",
        )

    cli = ProveKitCLI(binary_path=binary, runner=fake_runner, timeout_seconds=7)
    command = ProveKitCommand(
        (str(binary), "prove", "--input", private_input),
        sensitive_values=(private_input, private_axiom),
    )

    result = cli.run_command(command, cwd=tmp_path)

    assert result.ok is True
    assert captured["argv"] == [str(binary), "prove", "--input", private_input]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["timeout"] == 7
    assert private_input not in " ".join(result.command)
    assert private_input not in result.stdout
    assert private_axiom not in result.stdout
    assert SENSITIVE_REDACTION in result.stdout


def test_nonzero_result_is_structured_and_redacted(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    secret = "private witness literal"

    def fake_runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr=f"bad {secret}")

    cli = ProveKitCLI(binary_path=binary, runner=fake_runner)
    command = ProveKitCommand((str(binary), "prove"), sensitive_values=(secret,))

    result = cli.run_command(command)

    assert result.ok is False
    assert result.returncode == 9
    assert result.to_dict()["ok"] is False
    assert secret not in result.stderr
    with pytest.raises(ZKPError) as exc:
        result.raise_for_failure()
    assert secret not in str(exc.value)


def test_timeout_result_is_structured_and_redacted(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    secret = "axiom should not appear"

    def fake_runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=argv,
            timeout=kwargs["timeout"],
            output=f"stdout {secret}",
            stderr=f"stderr {secret}",
        )

    cli = ProveKitCLI(binary_path=binary, runner=fake_runner, timeout_seconds=3)
    command = ProveKitCommand((str(binary), "prove"), sensitive_values=(secret,))

    result = cli.run_command(command)

    assert result.ok is False
    assert result.timed_out is True
    assert result.returncode is None
    assert "timed out" in result.error
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_file_execution_failure_is_structured(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")

    def fake_runner(argv, **kwargs):
        raise FileNotFoundError(os.fsencode(argv[0]))

    cli = ProveKitCLI(binary_path=binary, runner=fake_runner)
    result = cli.run_command(ProveKitCommand((str(binary), "--help")))

    assert result.ok is False
    assert result.returncode is None
    assert "execution failed" in result.error

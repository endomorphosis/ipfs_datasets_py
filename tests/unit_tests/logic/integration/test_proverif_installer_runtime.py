"""Canonical runtime identity regressions for the ProVerif installer."""

from __future__ import annotations

from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.installers import proverif
from ipfs_datasets_py.logic.integration.bridges import prover_installer


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_proverif_probe_uses_canonical_help_and_exact_first_line(
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif",
        (
            'test "${1:-}" = "-help"\n'
            'echo "Proverif 2.05. Cryptographic protocol verifier"'
        ),
    )

    probe = proverif.probe_proverif_runtime(str(executable))

    assert probe.command == (str(executable), "-help")
    assert probe.returncode == 0
    assert probe.observed_version == proverif.PROVERIF_VERSION
    assert probe.usable is True


def test_proverif_probe_rejects_rc2_path_that_contains_locked_version(
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif-2.05" / "proverif",
        'echo "$0: unknown option \'-help\'" >&2\nexit 2',
    )

    probe = proverif.probe_proverif_runtime(str(executable))

    assert "proverif-2.05" in probe.output
    assert probe.returncode == 2
    assert probe.observed_version is None
    assert probe.usable is False
    assert probe.reason_code == "runtime_probe_nonzero_exit"


def test_proverif_probe_rejects_nonzero_canonical_looking_banner(
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif",
        'echo "Proverif 2.05. Cryptographic protocol verifier"\nexit 2',
    )

    probe = proverif.probe_proverif_runtime(str(executable))

    assert probe.observed_version == proverif.PROVERIF_VERSION
    assert probe.usable is False
    assert probe.reason_code == "runtime_probe_nonzero_exit"


def test_proverif_probe_rejects_unanchored_version_text(tmp_path: Path) -> None:
    executable = _write_executable(
        tmp_path / "proverif",
        (
            'echo "/cache/proverif-2.05/bin/proverif"\n'
            'echo "Proverif 2.05. Cryptographic protocol verifier"'
        ),
    )

    probe = proverif.probe_proverif_runtime(str(executable))

    assert probe.returncode == 0
    assert probe.observed_version is None
    assert probe.usable is False
    assert probe.reason_code == "runtime_version_unreadable"


def test_ensure_proverif_does_not_promote_failed_public_probe(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "install"
    executable = _write_executable(
        install_root / "bin" / proverif.PROVERIF_EXECUTABLE,
        'echo "$0: unknown option \'-help\'" >&2\nexit 2',
    )

    receipt = proverif.ensure_proverif(
        yes=False,
        strict=True,
        install_root=install_root,
        ensure_opam_first=False,
    )

    assert receipt.executable_path is None
    assert receipt.installed is False
    assert receipt.status == "failed"
    assert receipt.phase == "validation"
    assert "runtime_validation_failed" in receipt.reason_codes
    assert receipt.bindings["existing_runtime_probe"]["command"] == (
        str(executable.resolve()),
        "-help",
    )


def test_public_installer_status_rejects_rc2_proverif_path_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif-2.05" / "proverif",
        'echo "$0: unknown option \'-help\'" >&2\nexit 2',
    )
    monkeypatch.setattr(
        prover_installer,
        "_which",
        lambda name: str(executable) if name == "proverif" else None,
    )
    monkeypatch.setattr(prover_installer, "_managed_tlc_release", lambda _: "")
    monkeypatch.setattr(prover_installer, "_distribution_version", lambda _: "")
    monkeypatch.setattr(prover_installer, "_find_ergoai_binary", lambda: None)

    statuses = prover_installer.managed_solver_version_status()
    status = next(item for item in statuses if item["solver"] == "proverif")

    assert status["executable"] == str(executable)
    assert status["installed_version"] is None
    assert status["present"] is True
    assert status["status"] == "manual_update_required"
    assert status["manual_update_required"] is True
    assert prover_installer._read_version(str(executable)) == ""


def test_public_installer_version_match_uses_canonical_proverif_probe(
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif",
        (
            'test "${1:-}" = "-help"\n'
            'echo "Proverif 2.05. Cryptographic protocol verifier"'
        ),
    )

    assert (
        prover_installer._proverif_version_matches(
            str(executable),
            prover_installer.PROVERIF_VERSION,
        )
        is True
    )


def test_public_ensure_rejects_mismatched_existing_proverif(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = _write_executable(
        tmp_path / "proverif-2.05" / "proverif",
        'echo "$0: unknown option \'-help\'" >&2\nexit 2',
    )
    monkeypatch.setattr(prover_installer, "_which", lambda _: str(executable))

    assert (
        prover_installer.ensure_proverif(
            yes=False,
            strict=True,
        )
        is False
    )

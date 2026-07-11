"""Regression coverage for first-use native theorem-prover installation."""

from __future__ import annotations

from pathlib import Path


def _clear_lazy_install_environment(monkeypatch) -> None:
    for name in (
        "IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS",
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_execution_request_installs_native_solver_and_forwards_progress(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    _clear_lazy_install_environment(monkeypatch)
    lazy_installer.reset_lazy_install_attempts()
    calls: list[dict[str, object]] = []
    events = []

    def fake_ensure_apalache(**kwargs) -> bool:
        calls.append(dict(kwargs))
        kwargs["on_progress"]("installing", "downloading pinned Apalache release")
        kwargs["on_progress"]("installed", "Apalache launcher is ready")
        return True

    monkeypatch.setattr(prover_installer, "ensure_apalache", fake_ensure_apalache)
    monkeypatch.setattr(lazy_installer, "find_executable", lambda _name: None)

    assert lazy_installer.lazy_install_prover(
        "apalache",
        allow_automatic=True,
        reason="Xaman model check",
        progress=events.append,
    )
    assert calls[0]["yes"] is True
    assert calls[0]["strict"] is False
    assert callable(calls[0]["on_progress"])
    assert [event.phase for event in events] == [
        "checking",
        "installing",
        "installing",
        "installed",
        "installed",
    ]
    assert "Xaman model check" in events[1].message


def test_execution_request_respects_global_opt_out(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    lazy_installer.reset_lazy_install_attempts()
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "0")
    calls: list[dict[str, object]] = []
    events = []
    monkeypatch.setattr(
        prover_installer,
        "ensure_tamarin",
        lambda **kwargs: calls.append(dict(kwargs)) or True,
    )
    monkeypatch.setattr(lazy_installer, "find_executable", lambda _name: None)

    assert lazy_installer.ensure_prover_executable(
        "tamarin",
        reason="Xaman protocol execution",
        progress=events.append,
    ) is None
    assert calls == []
    assert events[-1].phase == "disabled"


def test_ergoai_explicit_binary_is_resolved_without_install(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer

    executable = tmp_path / "runErgo.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("ERGOAI_BINARY", str(executable))

    assert lazy_installer.ensure_prover_executable(
        "ergoai",
        reason="external proof execution",
    ) == str(executable)


def test_cvc5_cli_installer_uses_user_local_launcher_without_network(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setattr(prover_installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(prover_installer.platform, "machine", lambda: "x86_64")

    def fake_which(name: str) -> str | None:
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_download(_url, destination, _sha256, **_kwargs) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        return True

    def fake_extract(_archive: Path, destination: Path) -> None:
        executable = destination / "bin" / "cvc5"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_download_release_artifact", fake_download)
    monkeypatch.setattr(prover_installer, "_safe_extract_zip", fake_extract)

    assert prover_installer.ensure_cvc5_cli(yes=True, strict=True)
    launcher = root / "bin" / "cvc5"
    assert launcher.is_file()
    assert "exec" in launcher.read_text(encoding="utf-8")


def test_apalache_installer_handles_versioned_archive_root(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setattr(prover_installer, "_linux_x86_64", lambda: True)

    def fake_which(name: str) -> str | None:
        if name == "java":
            return "/fixture/java"
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_download(_url, destination, _sha256, **_kwargs) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        return True

    def fake_extract(_archive: Path, destination: Path) -> None:
        executable = destination / "apalache-0.58.3" / "bin" / "apalache-mc"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_download_release_artifact", fake_download)
    monkeypatch.setattr(prover_installer, "_safe_extract_tar", fake_extract)

    assert prover_installer.ensure_apalache(yes=True, strict=True)
    assert (root / "bin" / "apalache-mc").is_file()


def test_coq_opam_fallback_uses_isolated_user_local_root(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    opam_root = root / "opam"
    switch = "test-coq"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setenv("IPFS_DATASETS_PY_COQ_OPAM_SWITCH", switch)
    commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "opam":
            return "/fixture/opam"
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_run(command, *, check, env=None, cwd=None) -> int:
        commands.append(list(command))
        if command[1:3] == ["install", "rocq-prover"]:
            bin_dir = opam_root / switch / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ("coqc", "coqtop"):
                executable = bin_dir / name
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o755)
        return 0

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_run", fake_run)
    monkeypatch.setattr(prover_installer, "_run_custom_solver_installer", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(prover_installer, "_package_names_for", lambda *_args: [])

    assert prover_installer.ensure_coq(yes=True, strict=True)
    assert (root / "bin" / "coqc").is_file()
    assert any(command[1:3] == ["init", "--bare"] for command in commands)
    assert any(command[1:3] == ["install", "rocq-prover"] for command in commands)


def test_manual_update_forces_only_the_selected_solver(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        prover_installer,
        "ensure_apalache",
        lambda **kwargs: calls.append(dict(kwargs)) or True,
    )

    assert prover_installer.main(["--update", "--yes", "--apalache", "--strict"]) == 0
    assert calls == [{"yes": True, "strict": True, "force": True}]


def test_managed_version_check_is_read_only(monkeypatch, capsys) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    monkeypatch.setattr(
        prover_installer,
        "managed_solver_version_status",
        lambda: [
            {
                "solver": "apalache",
                "managed_version": "0.58.3",
                "installed_version": "0.58.3",
                "manual_update_required": False,
            }
        ],
    )

    assert prover_installer.main(["--check-updates", "--strict"]) == 0
    assert '"managed_solvers"' in capsys.readouterr().out


def test_optional_packaging_and_installation_documentation_are_present() -> None:
    root = Path(__file__).resolve().parents[4]
    setup = (root / "setup.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (root / "requirements-theorem-provers.txt").read_text(encoding="utf-8")
    documentation = (root / "docs/security_verification/lazy_theorem_prover_installation.md").read_text(
        encoding="utf-8"
    )

    assert "theorem-provers" in setup
    assert "theorem-provers" in pyproject
    assert "z3-solver" in requirements
    assert "cvc5" in requirements
    assert "symbolicai" in requirements
    assert "IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0" in documentation
    assert "ProverInstallEvent" in documentation
    assert "--check-updates" in documentation
    assert "Rocq `9.1.1`" in documentation

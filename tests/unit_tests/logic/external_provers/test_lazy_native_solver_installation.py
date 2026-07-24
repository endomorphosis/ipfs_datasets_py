"""Regression coverage for first-use native theorem-prover installation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


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


def test_parallel_first_use_installs_each_prover_once(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    _clear_lazy_install_environment(monkeypatch)
    lazy_installer.reset_lazy_install_attempts()
    calls: list[str] = []
    monkeypatch.setattr(
        prover_installer,
        "ensure_vampire",
        lambda **_kwargs: calls.append("vampire") or True,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: lazy_installer.lazy_install_prover(
                    "vampire",
                    allow_automatic=True,
                    reason="parallel Hammer route",
                ),
                range(8),
            )
        )

    assert results == [True] * 8
    assert calls == ["vampire"]


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
    monkeypatch.setattr(prover_installer.platform, "machine", lambda: "aarch64")
    downloaded: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_download(url, destination, sha256, **_kwargs) -> bool:
        downloaded["url"] = url
        downloaded["sha256"] = sha256
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        return True

    def fake_extract(_archive: Path, destination: Path) -> None:
        executable = destination / "bin" / "cvc5"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(
            "#!/bin/sh\nprintf 'This is cvc5 version 1.3.3\\n'\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_download_release_artifact", fake_download)
    monkeypatch.setattr(prover_installer, "_safe_extract_zip", fake_extract)

    assert prover_installer.ensure_cvc5_cli(yes=True, strict=True)
    launcher = root / "bin" / "cvc5"
    assert launcher.is_file()
    assert "exec" in launcher.read_text(encoding="utf-8")
    assert downloaded == {
        "url": (
            "https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.3/"
            "cvc5-Linux-arm64-static.zip"
        ),
        "sha256": "2572d01b142a6bfebdcb259f5a395f6228d2db5609f7dcc9a60851a5f1a58655",
    }


def test_cvc5_resolution_skips_broken_path_binary_for_managed_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer

    root = tmp_path / "provers"
    managed = root / "bin" / "cvc5"
    managed.parent.mkdir(parents=True)
    managed.write_text(
        "#!/bin/sh\nprintf 'This is cvc5 version 1.3.3\\n'\n",
        encoding="utf-8",
    )
    managed.chmod(0o755)
    incompatible = tmp_path / "path" / "cvc5"
    incompatible.parent.mkdir()
    incompatible.write_text("#!/bin/sh\nexit 126\n", encoding="utf-8")
    incompatible.chmod(0o755)

    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setattr(
        lazy_installer.shutil,
        "which",
        lambda command: str(incompatible) if command == "cvc5" else None,
    )

    assert lazy_installer.find_executable("cvc5") == str(managed)


def test_cvc5_resolution_accepts_explicit_portable_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer

    launcher = tmp_path / "cvc5-wasm"
    launcher.write_text(
        "#!/bin/sh\nprintf 'This is cvc5 version wasm-test\\n'\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("IPFS_DATASETS_PY_CVC5_EXECUTABLE", str(launcher))
    monkeypatch.setattr(lazy_installer.shutil, "which", lambda _command: None)

    assert lazy_installer.find_executable("cvc5") == str(launcher)


def test_apalache_installer_handles_versioned_archive_root(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setattr(prover_installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(prover_installer.platform, "machine", lambda: "aarch64")
    downloaded: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        if name == "java":
            return "/fixture/java"
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_download(url, destination, sha256, **_kwargs) -> bool:
        downloaded.update(url=url, sha256=sha256)
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
    assert downloaded["url"].endswith("/apalache-0.58.3.tgz")
    assert downloaded["sha256"] == prover_installer.APALACHE_PORTABLE_SHA256


def test_opam_bootstrap_uses_official_user_local_arm_binary(
    monkeypatch, tmp_path: Path
) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setattr(prover_installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(prover_installer.platform, "machine", lambda: "aarch64")
    downloaded: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_download(url, destination, sha256, **_kwargs) -> bool:
        downloaded.update(url=url, sha256=sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "#!/bin/sh\nprintf '2.5.2\\n'\n",
            encoding="utf-8",
        )
        destination.chmod(0o755)
        return True

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_download_release_artifact", fake_download)

    executable = prover_installer._ensure_opam_binary(
        allow_sudo=False,
        strict=True,
        on_progress=None,
    )

    assert executable == str(root / "bin" / "opam")
    assert downloaded == {
        "url": (
            "https://github.com/ocaml/opam/releases/download/2.5.2/"
            "opam-2.5.2-arm64-linux"
        ),
        "sha256": (
            "c4106ece84bcb60c68342573d2d6b4f0d6770ee088015c2216adc83d8854dcf9"
        ),
    }


def test_generation_portfolio_includes_flogic_authority() -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    assert "ergoai" in prover_installer.PROVER_PORTFOLIOS["legal_ir_generation"]
    assert "isabelle" not in prover_installer.PROVER_PORTFOLIOS["legal_ir_generation"]
    assert {"coq", "isabelle"}.issubset(
        prover_installer.PROVER_PORTFOLIOS["reconstruction"]
    )
    managed_install_keys = set(prover_installer.MANAGED_SOLVER_VERSIONS)
    managed_install_keys.discard("rocq")
    managed_install_keys.add("coq")
    assert "symbolicai" not in prover_installer.PROVER_PORTFOLIOS[
        "legal_ir_training"
    ]
    assert managed_install_keys - {"symbolicai"} <= set(
        prover_installer.PROVER_PORTFOLIOS["legal_ir_training"]
    )
    assert managed_install_keys.issubset(
        prover_installer.PROVER_PORTFOLIOS["legal_ir_full"]
    )


def test_portfolio_exclusion_omits_inherited_solver(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    calls: list[str] = []
    monkeypatch.setattr(
        prover_installer,
        "ensure_coq",
        lambda **_kwargs: calls.append("coq") or True,
    )
    monkeypatch.setattr(
        prover_installer,
        "ensure_isabelle",
        lambda **_kwargs: calls.append("isabelle") or True,
    )

    result = prover_installer.main(
        [
            "--portfolio",
            "reconstruction",
            "--exclude",
            "isabelle",
            "--yes",
            "--strict",
        ]
    )

    assert result == 0
    assert calls == ["coq"]


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
                executable.write_text(
                    "#!/bin/sh\necho 'The Rocq Prover, version 9.1.1'\n",
                    encoding="utf-8",
                )
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


def test_coq_opam_supports_unified_rocq_cli(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    opam_root = root / "opam"
    switch = "test-rocq"
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setenv("IPFS_DATASETS_PY_COQ_OPAM_SWITCH", switch)

    def fake_which(name: str) -> str | None:
        if name == "opam":
            return "/fixture/opam"
        launcher = root / "bin" / name
        return str(launcher) if launcher.is_file() else None

    def fake_run(command, *, check, env=None, cwd=None) -> int:
        if command[1:3] == ["install", "rocq-prover"]:
            bin_dir = opam_root / switch / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            executable = bin_dir / "rocq"
            executable.write_text(
                "#!/bin/sh\necho 'The Rocq Prover, version 9.1.1'\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
        return 0

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_run", fake_run)
    monkeypatch.setattr(
        prover_installer,
        "_run_custom_solver_installer",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(prover_installer, "_package_names_for", lambda *_args: [])

    assert prover_installer.ensure_coq(yes=True, strict=True)
    coqc_launcher = (root / "bin" / "coqc").read_text(encoding="utf-8")
    coqtop_launcher = (root / "bin" / "coqtop").read_text(encoding="utf-8")
    assert "rocq compile \"$@\"" in coqc_launcher
    assert "rocq repl \"$@\"" in coqtop_launcher


def test_existing_tamarin_requires_its_maude_runtime_validation(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        prover_installer,
        "_which",
        lambda name: "/fixture/tamarin-prover" if name == "tamarin-prover" else "/fixture/maude" if name == "maude" else None,
    )
    monkeypatch.setattr(prover_installer, "ensure_maude", lambda **_kwargs: True)
    monkeypatch.setattr(prover_installer, "_tamarin_accepts_maude", lambda *_args: False)

    assert not prover_installer.ensure_tamarin(
        yes=False,
        strict=True,
        on_progress=lambda phase, message: events.append((phase, message)),
    )
    assert events[-1][0] == "failed"
    assert "runtime validation" in events[-1][1]


def test_tamarin_runtime_receipt_accepts_actual_maude_version_format(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    monkeypatch.setattr(
        prover_installer.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                "tamarin-prover 1.12.0\n"
                "checking installation: OK.\n"
                "Generated from:\n"
                "Tamarin version 1.12.0\n"
                "Maude version 3.5.1\n"
            ),
            stderr="",
        ),
    )

    assert prover_installer._tamarin_accepts_maude(
        "/fixture/tamarin-prover",
        "/fixture/maude",
    )


def test_maude_compatibility_uses_tamarins_exact_release_allowlist(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    monkeypatch.setattr(prover_installer, "_read_version", lambda _path: "3.2")
    assert not prover_installer._maude_is_tamarin_compatible("/fixture/maude")

    monkeypatch.setattr(prover_installer, "_read_version", lambda _path: "3.2.1")
    assert prover_installer._maude_is_tamarin_compatible("/fixture/maude")

    monkeypatch.setattr(prover_installer, "_read_version", lambda _path: "3.5.1")
    assert prover_installer._maude_is_tamarin_compatible("/fixture/maude")


def test_incompatible_existing_maude_is_repaired_automatically(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(prover_installer, "_which", lambda name: f"/fixture/{name}")
    monkeypatch.setattr(
        prover_installer,
        "_maude_is_tamarin_compatible",
        lambda path: path == "/fixture/repaired-maude",
    )
    monkeypatch.setattr(
        prover_installer,
        "_run_custom_solver_installer",
        lambda *_args, **_kwargs: True,
    )

    assert prover_installer.ensure_maude(
        yes=True,
        strict=True,
        on_progress=lambda phase, message: events.append((phase, message)),
    )
    assert events[0][0] == "installing"
    assert "repairing" in events[0][1]


def test_proverif_bootstraps_an_isolated_opam_ocaml_toolchain(monkeypatch, tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    root = tmp_path / "provers"
    switch = "test-proverif"
    commands: list[list[str]] = []
    monkeypatch.setenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", str(root))
    monkeypatch.setenv("IPFS_DATASETS_PY_PROVERIF_OPAM_SWITCH", switch)

    def fake_which(name: str) -> str | None:
        if name == "opam":
            return "/fixture/opam"
        return None

    def fake_run(command, *, check, env=None, cwd=None) -> int:
        commands.append(list(command))
        if command[1:3] == ["switch", "create"]:
            bin_dir = root / "opam" / switch / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ("ocamlopt", "ocamlyacc", "ocamllex"):
                executable = bin_dir / name
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o755)
        return 0

    monkeypatch.setattr(prover_installer, "_which", fake_which)
    monkeypatch.setattr(prover_installer, "_run", fake_run)

    environment = prover_installer._proverif_build_environment(
        allow_sudo=False,
        strict=True,
        on_progress=None,
        force=False,
    )

    assert environment is not None
    assert environment["OPAMSWITCH"] == switch
    assert environment["PATH"].split(":")[0] == str(root / "opam" / switch / "bin")
    assert any(command[1:3] == ["switch", "create"] for command in commands)


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

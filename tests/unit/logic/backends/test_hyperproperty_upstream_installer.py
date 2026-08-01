from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from types import MappingProxyType

import pytest
from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executable(path: Path, content: bytes = b"synthetic dependency\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)
    return path.resolve()


def _archive(
    tmp_path: Path,
    *,
    name: str,
    commit: str,
    files: dict[str, bytes],
) -> Path:
    tree = tmp_path / f"{name}-{commit}"
    tree.mkdir()
    for relative, content in files.items():
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    archive = tmp_path / f"{name}-{commit}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(tree, arcname=tree.name)
    shutil.rmtree(tree)
    return archive


def _dependency_identities(tmp_path: Path, tool_id: str) -> tuple[hp.DependencyIdentity, ...]:
    names = {
        hp.TOOL_HYPERLTL: ("make", "ocamlc"),
        hp.TOOL_AUTOHYPER: ("dotnet", "autfilt", "ltl2tgba"),
        hp.TOOL_MCHYPER: ("ghc", "python2.7", "abc", "aigtoaig"),
    }[tool_id]
    result = []
    for name in names:
        executable = _executable(tmp_path / "dependencies" / name)
        result.append(
            hp.DependencyIdentity(
                name=name,
                constraint="test-pinned",
                executable=str(executable),
                version_output=f"{name} synthetic-reviewed-version",
                executable_sha256=_sha256(executable),
                phase=(
                    "runtime"
                    if name in {"autfilt", "ltl2tgba", "python2.7", "abc", "aigtoaig"}
                    else "build"
                ),
            )
        )
    return tuple(result)


def _install_synthetic_upstream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool_id: str,
) -> tuple[hp.EngineIdentity, Path, dict[str, str]]:
    commit = {
        hp.TOOL_HYPERLTL: "1" * 40,
        hp.TOOL_AUTOHYPER: "2" * 40,
        hp.TOOL_MCHYPER: "3" * 40,
    }[tool_id]
    files = {
        hp.TOOL_HYPERLTL: {"Makefile": b"all:\n\t@true\n"},
        hp.TOOL_AUTOHYPER: {
            "app/paths.json": b"{}\n",
            "src/AutoHyper/AutoHyper.fsproj": b"<Project />\n",
        },
        hp.TOOL_MCHYPER: {
            "mchyper.py": (
                b"#!/usr/bin/env python2.7\n"
                b"# official upstream entry point fixture\n"
                b"print('mchyper')\n"
            ),
            "src/Main.hs": b"main = putStrLn \"MCHyper\"\n",
        },
    }[tool_id]
    main_archive = _archive(
        tmp_path,
        name=f"fixture-{tool_id}",
        commit=commit,
        files=files,
    )
    source_url = f"https://github.com/example/{tool_id}"
    archive_url = f"{source_url}/archive/{commit}.tar.gz"
    pin = dict(hp.DEFAULT_PINS[tool_id])
    pin.update(
        {
            "artifact_url": archive_url,
            "git_commit": commit,
            "release_tag": commit,
            "sha256": _sha256(main_archive),
            "source": source_url,
            "version": commit[:8],
        }
    )
    defaults = {name: dict(value) for name, value in hp.DEFAULT_PINS.items()}
    defaults[tool_id] = pin
    monkeypatch.setattr(hp, "DEFAULT_PINS", MappingProxyType(defaults))
    monkeypatch.setattr(
        hp,
        "pin_for_tool",
        lambda selected, **_kwargs: dict(defaults[selected]),
    )
    monkeypatch.setattr(hp, "tool_supported_on_platform", lambda *_args, **_kwargs: True)

    archives = {archive_url: main_archive}
    if tool_id == hp.TOOL_AUTOHYPER:
        components: dict[str, MappingProxyType[str, str]] = {}
        for index, name in enumerate(
            ("FsOmegaLib", "TransitionSystemLib"), start=4
        ):
            component_commit = str(index) * 40
            component_url = (
                f"https://github.com/example/{name}/archive/"
                f"{component_commit}.tar.gz"
            )
            component_archive = _archive(
                tmp_path,
                name=f"fixture-{name}",
                commit=component_commit,
                files={"Library.fs": f"module {name}\n".encode()},
            )
            archives[component_url] = component_archive
            components[name] = MappingProxyType(
                {
                    "path": f"src/{name}",
                    "source": f"https://github.com/example/{name}",
                    "git_commit": component_commit,
                    "source_archive_url": component_url,
                    "source_archive_sha256": _sha256(component_archive),
                }
            )
        monkeypatch.setattr(
            hp, "AUTOHYPER_SOURCE_COMPONENTS", MappingProxyType(components)
        )

    def fake_download(url: str, destination: Path, expected: str) -> Path:
        source = archives[url]
        assert _sha256(source) == expected
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    dependencies = _dependency_identities(tmp_path, tool_id)
    monkeypatch.setattr(hp, "_download_verified_archive", fake_download)
    monkeypatch.setattr(
        hp,
        "_resolve_vendor_dependencies",
        lambda _tool, **_kwargs: dependencies,
    )

    def fake_build(argv: tuple[str, ...], *, cwd: Path, environment=None) -> None:
        del environment
        if tool_id == hp.TOOL_HYPERLTL:
            _executable(cwd / "eahyper_src" / "eahyper.native", b"\x7fELF-eahyper")
            _executable(cwd / "LTL_SAT_solver" / "aalta", b"\x7fELF-aalta")
            _executable(cwd / "LTL_SAT_solver" / "pltl", b"\x7fELF-pltl")
        elif tool_id == hp.TOOL_AUTOHYPER:
            if "restore" in argv:
                (cwd / "packages.lock.json").write_text(
                    '{"version": 1, "dependencies": {}}\n', encoding="utf-8"
                )
            if "build" in argv:
                _executable(cwd.parent.parent / "app" / "AutoHyper", b"\x7fELF-autohyper")
        else:
            _executable(cwd / "Main", b"\x7fELF-mchyper-kernel")

    monkeypatch.setattr(hp, "_run_build_command", fake_build)
    install_root = tmp_path / "install"
    identity = hp.materialize_vendor_engine(
        tool_id,
        install_root=install_root,
        repo_root=tmp_path / "no-lock",
        platform_id=hp.LINUX_X86_64,
    )
    return identity, install_root, pin


@pytest.mark.parametrize(
    ("ensure", "reason"),
    [
        (hp.ensure_hyperltl, "missing_dependency:ocamlc"),
        (hp.ensure_autohyper, "missing_dependency:dotnet"),
        (hp.ensure_mchyper, "missing_dependency:ghc"),
    ],
)
def test_vendor_install_preserves_explicit_dependency_blockers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ensure,
    reason: str,
) -> None:
    monkeypatch.setattr(hp, "_gate_install", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(hp, "tool_supported_on_platform", lambda *_args, **_kwargs: True)

    def blocked(_tool: str, **_kwargs):
        raise hp.HyperpropertyInstallBlocked("dependency unavailable", reason)

    monkeypatch.setattr(hp, "_resolve_vendor_dependencies", blocked)
    install_root = tmp_path / "install"

    receipt = ensure(
        yes=True,
        strict=False,
        vendor=True,
        install_root=install_root,
        platform_id=hp.LINUX_X86_64,
    )

    assert receipt.status == "blocked"
    assert receipt.block_reasons == (reason,)
    assert not install_root.exists()


@pytest.mark.parametrize("tool_id", hp.EXTERNAL_TOOLS)
def test_synthetic_upstream_builds_are_identity_bound_without_adapter_shims(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool_id: str,
) -> None:
    identity, _install_root, _pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )

    assert identity.is_vendor_build is True
    assert identity.is_upstream_build is True
    assert identity.is_hermetic_engine is False
    assert identity.executable_kind in {
        "upstream_compiled_binary",
        "upstream_python_entrypoint",
    }
    assert identity.dependency_identities
    assert identity.source_tree_sha256
    assert identity.distribution_tree_sha256
    assert not hp._is_internal_python_adapter(Path(identity.executable))
    if tool_id == hp.TOOL_MCHYPER:
        assert identity.executable_kind == "upstream_python_entrypoint"
        assert Path(identity.executable).read_bytes().startswith(
            b"#!/usr/bin/env python2.7"
        )
    else:
        assert Path(identity.executable).read_bytes().startswith(b"\x7fELF")
    if tool_id == hp.TOOL_HYPERLTL:
        solver_dir = Path(dict(identity.runtime_environment)["EAHYPER_SOLVER_DIR"])
        assert solver_dir.is_dir()
        assert solver_dir.name == "LTL_SAT_solver"


def test_explicit_dotnet_and_spot_roots_are_resolved_and_hash_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dotnet = _executable(tmp_path / "dotnet-sdk" / "dotnet", b"dotnet-sdk\n")
    autfilt = _executable(tmp_path / "spot" / "bin" / "autfilt", b"autfilt\n")
    ltl2tgba = _executable(tmp_path / "spot" / "bin" / "ltl2tgba", b"ltl2tgba\n")
    versions = {
        str(dotnet): "8.0.300",
        str(autfilt): "Spot 2.12",
        str(ltl2tgba): "Spot 2.12",
    }
    monkeypatch.setattr(hp.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        hp,
        "_capture_dependency_version",
        lambda executable, _args, **_kwargs: versions[executable],
    )

    identities = hp._resolve_vendor_dependencies(
        hp.TOOL_AUTOHYPER,
        dependency_roots={
            "dotnet-sdk": dotnet.parent,
            "spot": autfilt.parent.parent,
        },
    )

    by_name = {item.name: item for item in identities}
    assert set(by_name) == {"dotnet", "autfilt", "ltl2tgba"}
    assert by_name["dotnet"].executable == str(dotnet)
    assert by_name["autfilt"].executable == str(autfilt)
    assert by_name["ltl2tgba"].executable == str(ltl2tgba)
    for item in identities:
        assert item.executable_sha256 == _sha256(Path(item.executable))


def test_eahyper_build_uses_reviewed_gcc13_compatibility_recipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    make = _executable(tmp_path / "opam" / "bin" / "make")
    ocamlc = _executable(tmp_path / "opam" / "bin" / "ocamlc")
    dependencies = tuple(
        hp.DependencyIdentity(
            name=name,
            constraint="reviewed",
            executable=str(path),
            version_output="reviewed",
            executable_sha256=_sha256(path),
        )
        for name, path in (("make", make), ("ocamlc", ocamlc))
    )
    source = tmp_path / "source"
    source.mkdir()
    observed_environment: dict[str, str] = {}

    def fake_build(argv, *, cwd: Path, environment=None) -> None:
        assert argv == (str(make), "RELEASEFLAG=-O2 -fpermissive")
        observed_environment.update(environment or {})
        _executable(cwd / "eahyper_src" / "eahyper.native", b"\x7fELF-eahyper")
        _executable(cwd / "LTL_SAT_solver" / "aalta", b"\x7fELF-aalta")
        _executable(cwd / "LTL_SAT_solver" / "pltl", b"\x7fELF-pltl")

    monkeypatch.setattr(hp, "_run_build_command", fake_build)

    hp._build_upstream_source(hp.TOOL_HYPERLTL, source, dependencies)

    assert observed_environment["RELEASEFLAG"] == "-O2 -fpermissive"
    assert str(make.parent) in observed_environment["PATH"].split(":")


def test_tampered_upstream_executable_is_not_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, hp.TOOL_HYPERLTL
    )
    Path(identity.executable).write_bytes(b"tampered")

    assert (
        hp._identity_from_disk(
            hp.TOOL_HYPERLTL, install_root, pin, vendor=True
        )
        is None
    )


def test_generated_python_adapter_cannot_be_forged_into_vendor_identity(
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    pin = dict(hp.DEFAULT_PINS[tool_id])
    version_root = (
        tmp_path / "hyperproperty-vendor" / tool_id / pin["version"]
    )
    executable = version_root / "bin" / tool_id
    source = hp.build_engine_shim_source(
        tool_id,
        pin["version"],
        identity_file=str(version_root / "identity.json"),
        is_vendor_build=False,
    )
    executable.parent.mkdir(parents=True)
    executable.write_text(source, encoding="utf-8")
    executable.chmod(0o755)
    manifest = {
        "artifact_sha256": _sha256(executable),
        "executable": str(executable),
        "executable_kind": "upstream_compiled_binary",
        "executable_origin": f"bin/{tool_id}",
        "is_hermetic_engine": False,
        "is_upstream_build": True,
        "is_vendor_build": True,
        "tool_id": tool_id,
        "version": pin["version"],
    }
    (version_root / "identity.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    assert hp._identity_from_disk(tool_id, tmp_path, pin, vendor=True) is None


def test_python_adapter_factory_refuses_vendor_label() -> None:
    with pytest.raises(
        hp.HyperpropertyInstallerError,
        match="cannot be labeled vendor/native",
    ):
        hp.build_engine_shim_source(
            hp.TOOL_HYPERLTL,
            "test",
            identity_file="/tmp/not-created",
            is_vendor_build=True,
        )

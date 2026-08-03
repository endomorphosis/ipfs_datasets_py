from __future__ import annotations

import hashlib
import json
import os
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


def _make_sealed_test_tree(version_root: Path, install_root: Path) -> None:
    """Remove writes from a synthetic deployment; tests substitute its UID."""

    for path in sorted(
        (version_root, *version_root.rglob("*")),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    component = version_root.parent
    while True:
        component.chmod(component.stat().st_mode & ~0o222)
        if component == install_root:
            break
        component = component.parent


def _seal_relocated_test_tree(
    monkeypatch: pytest.MonkeyPatch,
    version_root: Path,
    install_root: Path,
) -> Path:
    """Seal a test tree through a substitute ancestor trust boundary."""

    boundary = install_root.parent
    monkeypatch.setattr(hp, "_SEALED_DEPLOYMENT_OWNER_UID", os.getuid())
    monkeypatch.setattr(
        hp, "_SEALED_DEPLOYMENT_ANCESTOR_BOUNDARY", boundary
    )
    _make_sealed_test_tree(version_root, install_root)
    boundary.chmod(boundary.stat().st_mode & ~0o222)
    return boundary


def _make_test_tree_writable(install_root: Path) -> None:
    """Restore owner writes so pytest can clean a synthetic sealed tree."""

    if not install_root.exists():
        return
    install_root.chmod(install_root.stat().st_mode | 0o700)
    for path in sorted(
        install_root.rglob("*"), key=lambda item: len(item.parts)
    ):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o700)


def _unseal_relocated_test_tree(
    install_root: Path,
    boundary: Path,
) -> None:
    boundary.chmod(boundary.stat().st_mode | 0o700)
    _make_test_tree_writable(install_root)


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
            "src/AutoHyper/Configuration.fs": (
                b"module Configuration\n\n"
                b"let getSolverConfiguration () =\n"
                b"    let solverConfig = "
                b"parseSolverConfigurationContent configContent\n"
            ),
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

    install_root = tmp_path / "install"
    dependencies = _dependency_identities(install_root, tool_id)
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
    dependency_roots: dict[str, Path] = {}
    if tool_id == hp.TOOL_MCHYPER:
        provenance_root = install_root / "build-dependencies" / "mchyper"
        package_db = provenance_root / "ghc-package-db"
        package_db.mkdir(parents=True)
        (package_db / "package.cache").write_bytes(b"synthetic package db\n")
        dependency_roots["ghc-package-db"] = package_db
        for name, content in (
            ("aiger", b"aiger reviewed source\n"),
            ("abc", b"abc reviewed source\n"),
            ("python", b"python reviewed source\n"),
        ):
            source_root = provenance_root / f"{name}-source"
            source_root.mkdir(parents=True)
            (source_root / "SOURCE").write_bytes(content)
            if name == "aiger":
                (source_root / "VERSION").write_text(
                    hp.MCHYPER_AIGER_VERSION, encoding="utf-8"
                )
            archive = provenance_root / f"{name}-source.tar.gz"
            archive.write_bytes(content + b"archive\n")
            dependency_roots[f"{name}-source"] = source_root
            dependency_roots[f"{name}-archive"] = archive
            monkeypatch.setattr(
                hp,
                {
                    "aiger": "MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256",
                    "abc": "MCHYPER_ABC_SOURCE_ARCHIVE_SHA256",
                    "python": "MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256",
                }[name],
                _sha256(archive),
            )
    identity = hp.materialize_vendor_engine(
        tool_id,
        install_root=install_root,
        repo_root=tmp_path / "no-lock",
        platform_id=hp.LINUX_X86_64,
        dependency_roots=dependency_roots,
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
    assert identity.distribution_content_tree_sha256
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
    if tool_id == hp.TOOL_AUTOHYPER:
        paths = json.loads(
            (
                Path(identity.executable).parent / "paths.json"
            ).read_text(encoding="utf-8")
        )
        assert paths == {
            "autfilt": "../../spot/autfilt",
            "ltl2tgba": "../../spot/ltl2tgba",
        }
        assert {
            "upstream/app/paths.json",
            "upstream/src/AutoHyper/Configuration.fs",
        }.issubset(dict(identity.build_lockfiles))
    if tool_id == hp.TOOL_MCHYPER:
        assert {
            "ghc-package-db",
            "aiger-source",
            "abc-source",
            "python-source",
        } == {item.name for item in identity.dependency_artifacts}
        runtime_path = dict(identity.runtime_environment)["PATH"].split(":")
        python_identity = next(
            item
            for item in identity.dependency_identities
            if item.name == "python2.7"
        )
        assert Path(runtime_path[0]) == Path(python_identity.executable).parent
        assert all("lift_coding" not in item for item in runtime_path)


@pytest.mark.parametrize("tool_id", hp.EXTERNAL_TOOLS)
def test_vendor_identity_rebinds_and_rehashes_after_common_tree_relocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool_id: str,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = (
        tmp_path
        / "opt"
        / "ipfs-accelerate"
        / "formal-toolchains"
        / "deployment-test"
        / "provers"
    )
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)

    relocated = hp._identity_from_disk(
        tool_id, relocated_root, pin, vendor=True
    )

    assert relocated is not None
    assert relocated.artifact_sha256 == identity.artifact_sha256
    assert relocated.distribution_tree_sha256 == identity.distribution_tree_sha256
    assert relocated.executable.startswith(str(relocated_root))
    assert relocated.source_archive_path.startswith(str(relocated_root))
    assert str(install_root) not in relocated.executable
    assert str(install_root) not in relocated.source_archive_path
    for dependency in relocated.dependency_identities:
        assert str(install_root) not in dependency.executable
        assert Path(dependency.executable).is_file()
    for artifact in relocated.dependency_artifacts:
        assert str(install_root) not in artifact.path
        assert Path(artifact.path).exists()
        if artifact.source_archive_path:
            assert str(install_root) not in artifact.source_archive_path
            assert Path(artifact.source_archive_path).is_file()
    for value in dict(relocated.runtime_environment).values():
        assert str(install_root) not in value


def test_legacy_manifest_remains_valid_after_mode_preserving_relocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    original_manifest = hp.identity_manifest_path(
        install_root, tool_id, pin["version"], vendor=True
    )
    payload = json.loads(original_manifest.read_text(encoding="utf-8"))
    payload.pop("distribution_content_tree_sha256")
    original_manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    relocated_root = tmp_path / "mode-preserving" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)

    relocated = hp._identity_from_disk(
        tool_id, relocated_root, pin, vendor=True
    )

    assert relocated is not None
    assert relocated.distribution_content_tree_sha256 == ""


@pytest.mark.parametrize("tool_id", hp.EXTERNAL_TOOLS)
def test_vendor_identity_accepts_only_content_exact_sealed_mode_normalization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool_id: str,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    version_root = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    ).parent
    boundary = _seal_relocated_test_tree(
        monkeypatch, version_root, relocated_root
    )
    try:
        relocated = hp._identity_from_disk(
            tool_id, relocated_root, pin, vendor=True
        )
        assert relocated is not None
        assert (
            relocated.distribution_content_tree_sha256
            == identity.distribution_content_tree_sha256
        )
        assert relocated.executable.startswith(str(relocated_root))
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_sealed_mode_normalization_rejects_legacy_manifest_without_content_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.pop("distribution_content_tree_sha256")
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    try:
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


@pytest.mark.parametrize("tamper", ("changed_byte", "added_name"))
def test_sealed_mode_normalization_rejects_content_or_name_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    if tamper == "added_name":
        (manifest.parent / "unexpected-file").write_bytes(b"not installed\n")
    else:
        makefile = manifest.parent / "upstream" / "Makefile"
        makefile.write_bytes(makefile.read_bytes() + b"# changed after copy\n")
    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    try:
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


@pytest.mark.parametrize("writable_kind", ("file", "directory"))
def test_sealed_mode_normalization_rejects_one_writable_tree_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    writable_kind: str,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    target = (
        manifest.parent / "upstream"
        if writable_kind == "directory"
        else manifest.parent / "upstream" / "Makefile"
    )
    target.chmod(target.stat().st_mode | 0o200)
    try:
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_sealed_mode_normalization_rejects_writable_ancestor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    boundary.chmod(boundary.stat().st_mode | 0o020)
    try:
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_sealed_mode_normalization_rejects_unsealed_or_wrong_owner_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "relocated" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    # One mode change selects the fallback, but the writable tree must fail.
    executable = manifest.parent / "upstream" / "eahyper_src" / "eahyper.native"
    executable.chmod(executable.stat().st_mode & ~0o222)
    monkeypatch.setattr(hp, "_SEALED_DEPLOYMENT_OWNER_UID", os.getuid())
    assert (
        hp._identity_from_disk(tool_id, relocated_root, pin, vendor=True)
        is None
    )

    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    try:
        monkeypatch.setattr(
            hp, "_SEALED_DEPLOYMENT_OWNER_UID", os.getuid() + 1
        )
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_sealed_mode_normalization_rejects_unsafe_link_even_if_digest_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    shutil.rmtree(install_root)
    manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    (manifest.parent / "unsafe-link").symlink_to("/etc/passwd")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["distribution_content_tree_sha256"] = hp._tree_content_sha256(
        manifest.parent, exclude=("identity.json",)
    )
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    boundary = _seal_relocated_test_tree(
        monkeypatch, manifest.parent, relocated_root
    )
    try:
        assert (
            hp._identity_from_disk(
                tool_id, relocated_root, pin, vendor=True
            )
            is None
        )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_mode_drift_at_recorded_root_never_uses_sealed_relocation_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    manifest = hp.identity_manifest_path(
        install_root, tool_id, pin["version"], vendor=True
    )
    executable = manifest.parent / "upstream" / "eahyper_src" / "eahyper.native"
    executable.chmod(executable.stat().st_mode & ~0o222)
    assert (
        hp._identity_from_disk(tool_id, install_root, pin, vendor=True)
        is None
    )


def test_relocation_identity_writer_validates_original_and_sealed_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    original_manifest = hp.identity_manifest_path(
        install_root, tool_id, pin["version"], vendor=True
    )
    original_payload = json.loads(
        original_manifest.read_text(encoding="utf-8")
    )
    original_payload.pop("distribution_content_tree_sha256")
    original_manifest.write_text(
        json.dumps(original_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    relocated_manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    boundary = _seal_relocated_test_tree(
        monkeypatch, relocated_manifest.parent, relocated_root
    )
    output = tmp_path / "enriched-identity.json"
    try:
        written = hp.write_sealed_vendor_relocation_identity(
            tool_id,
            original_install_root=install_root,
            relocated_install_root=relocated_root,
            output_path=output,
            repo_root=tmp_path / "no-lock",
        )
        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload["distribution_tree_sha256"] == (
            identity.distribution_tree_sha256
        )
        assert payload["distribution_content_tree_sha256"] == (
            identity.distribution_content_tree_sha256
        )
        assert "distribution_content_tree_sha256" not in original_payload
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_relocation_identity_writer_refuses_changed_original_distribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_id = hp.TOOL_HYPERLTL
    _identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, tool_id
    )
    relocated_root = tmp_path / "sealed" / "provers"
    shutil.copytree(install_root, relocated_root)
    relocated_manifest = hp.identity_manifest_path(
        relocated_root, tool_id, pin["version"], vendor=True
    )
    original_manifest = hp.identity_manifest_path(
        install_root, tool_id, pin["version"], vendor=True
    )
    original_executable = (
        original_manifest.parent
        / "upstream"
        / "eahyper_src"
        / "eahyper.native"
    )
    original_executable.chmod(original_executable.stat().st_mode & ~0o222)
    boundary = _seal_relocated_test_tree(
        monkeypatch, relocated_manifest.parent, relocated_root
    )
    try:
        with pytest.raises(
            hp.HyperpropertyInstallerError,
            match="original vendor identity failed full validation",
        ):
            hp.write_sealed_vendor_relocation_identity(
                tool_id,
                original_install_root=install_root,
                relocated_install_root=relocated_root,
                output_path=tmp_path / "must-not-exist.json",
                repo_root=tmp_path / "no-lock",
            )
    finally:
        _unseal_relocated_test_tree(relocated_root, boundary)


def test_relocated_loader_does_not_require_original_repo_lock_path(
    tmp_path: Path,
) -> None:
    for tool_id in hp.EXTERNAL_TOOLS:
        assert hp.pin_for_tool(
            tool_id, repo_root=tmp_path / "supervisor-worktree-without-lock"
        ) == dict(hp.DEFAULT_PINS[tool_id])


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


def test_mchyper_ghc_packages_use_one_explicit_package_db_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ghc_pkg = _executable(tmp_path / "ghcup" / "ghc-pkg")
    package_db = tmp_path / "cabal" / "package.db"
    package_db.mkdir(parents=True)
    observed: list[tuple[tuple[str, ...], dict[str, str]]] = []

    monkeypatch.setattr(
        hp,
        "_dependency_specs",
        lambda _tool: (
            {
                "name": "ghc-pkg",
                "candidates": ("ghc-pkg",),
                "args": ("--version",),
                "constraint": "",
            },
        ),
    )

    def capture(_executable, args, *, environment=None, **_kwargs):
        observed.append((tuple(args), dict(environment or {})))
        if tuple(args) == ("--version",):
            return "GHC package manager version 9.4.7"
        package = args[1]
        return f"id: {package}-1.2.3-reviewed\nversion: 1.2.3"

    monkeypatch.setattr(hp, "_capture_dependency_version", capture)
    identities = hp._resolve_vendor_dependencies(
        hp.TOOL_MCHYPER,
        dependency_roots={
            "ghc-pkg": ghc_pkg,
            "ghc-package-db": package_db,
        },
    )

    assert {item.name for item in identities} == {
        "ghc-pkg",
        "haskell-package:parsec",
        "haskell-package:hashable",
        "haskell-package:MissingH",
    }
    package_calls = observed[1:]
    assert [args for args, _environment in package_calls] == [
        ("field", "parsec", "id,version"),
        ("field", "hashable", "id,version"),
        ("field", "MissingH", "id,version"),
    ]
    assert all(
        environment["GHC_PACKAGE_PATH"] == f"{package_db}:"
        for _args, environment in package_calls
    )


def test_mchyper_rejects_ambiguous_ghc_package_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ghc_pkg = _executable(tmp_path / "ghcup" / "ghc-pkg")
    package_db = tmp_path / "cabal" / "package.db"
    package_db.mkdir(parents=True)
    monkeypatch.setattr(
        hp,
        "_dependency_specs",
        lambda _tool: (
            {
                "name": "ghc-pkg",
                "candidates": ("ghc-pkg",),
                "args": ("--version",),
                "constraint": "",
            },
        ),
    )

    def capture(_executable, args, **_kwargs):
        if tuple(args) == ("--version",):
            return "GHC package manager version 9.4.7"
        package = args[1]
        return (
            f"id: {package}-1.0\nversion: 1.0\n"
            f"id: {package}-2.0\nversion: 2.0"
        )

    monkeypatch.setattr(hp, "_capture_dependency_version", capture)
    with pytest.raises(
        hp.HyperpropertyInstallBlocked,
        match="GHC package parsec is not installed",
    ) as blocked:
        hp._resolve_vendor_dependencies(
            hp.TOOL_MCHYPER,
            dependency_roots={
                "ghc-pkg": ghc_pkg,
                "ghc-package-db": package_db,
            },
        )
    assert "missing_dependency:haskell-package:parsec" in blocked.value.block_reasons


def test_aiger_version_uses_verified_source_evidence_without_banner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "aiger-source"
    source.mkdir()
    (source / "VERSION").write_text(
        hp.MCHYPER_AIGER_VERSION, encoding="utf-8"
    )
    archive = tmp_path / "aiger.tar.gz"
    archive.write_bytes(b"reviewed aiger archive")
    monkeypatch.setattr(
        hp, "MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256", _sha256(archive)
    )

    evidence = hp._verified_aiger_version_evidence(
        {"aiger-source": source, "aiger-archive": archive}
    )

    assert evidence.startswith("1.9.4 (verified VERSION")
    archive.write_bytes(b"tampered")
    with pytest.raises(
        hp.HyperpropertyInstallBlocked,
        match="archive digest",
    ):
        hp._verified_aiger_version_evidence(
            {"aiger-source": source, "aiger-archive": archive}
        )


def test_mchyper_build_environment_extends_explicit_ghc_package_db(
    tmp_path: Path,
) -> None:
    ghc = _executable(tmp_path / "ghcup" / "ghc")
    dependency = hp.DependencyIdentity(
        name="ghc",
        constraint=">=8.4",
        executable=str(ghc),
        version_output="9.4.7",
        executable_sha256=_sha256(ghc),
    )
    package_db = tmp_path / "cabal" / "package.db"
    package_db.mkdir(parents=True)

    environment = hp._dependency_build_environment(
        (dependency,), {"ghc-package-db": package_db}
    )

    assert environment["GHC_PACKAGE_PATH"] == f"{package_db}:"
    assert str(ghc.parent) in environment["PATH"].split(":")


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


def test_symlinked_external_identity_manifest_is_not_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, hp.TOOL_HYPERLTL
    )
    manifest = hp.identity_manifest_path(
        install_root,
        identity.tool_id,
        identity.version,
        vendor=True,
    )
    external_manifest = tmp_path / "outside-managed-tree" / "identity.json"
    external_manifest.parent.mkdir()
    external_manifest.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(external_manifest)

    assert (
        hp._identity_from_disk(
            identity.tool_id, install_root, pin, vendor=True
        )
        is None
    )


def test_symlinked_install_root_is_not_a_canonical_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, hp.TOOL_HYPERLTL
    )
    install_alias = tmp_path / "install-alias"
    install_alias.symlink_to(install_root, target_is_directory=True)

    assert (
        hp._identity_from_disk(
            identity.tool_id, install_alias, pin, vendor=True
        )
        is None
    )


@pytest.mark.parametrize("origin_kind", ("absolute", "traversal"))
def test_non_relative_or_traversal_executable_origin_is_not_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin_kind: str,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, hp.TOOL_HYPERLTL
    )
    manifest = hp.identity_manifest_path(
        install_root,
        identity.tool_id,
        identity.version,
        vendor=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if origin_kind == "absolute":
        payload["executable_origin"] = identity.executable
    else:
        payload["executable_origin"] = (
            f"../{identity.version}/{payload['executable_origin']}"
        )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert (
        hp._identity_from_disk(
            identity.tool_id, install_root, pin, vendor=True
        )
        is None
    )


def test_tampered_mchyper_dependency_artifact_is_not_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity, install_root, pin = _install_synthetic_upstream(
        monkeypatch, tmp_path, hp.TOOL_MCHYPER
    )
    package_db = next(
        item
        for item in identity.dependency_artifacts
        if item.name == "ghc-package-db"
    )
    (Path(package_db.path) / "package.cache").write_bytes(b"tampered")

    assert (
        hp._identity_from_disk(
            hp.TOOL_MCHYPER, install_root, pin, vendor=True
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

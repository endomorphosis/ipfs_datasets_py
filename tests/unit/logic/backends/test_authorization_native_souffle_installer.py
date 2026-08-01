from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.backends.installers import authorization as installer


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compile_native_souffle(executable: Path) -> Path:
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("native compiler is required for Soufflé artifact tests")
    source = executable.parent / "souffle-fixture.c"
    executable.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        """
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--version") == 0) {
        puts("Version: 2.4.1");
        return 0;
    }
    puts("authz_result\\nALLOW");
    return 0;
}
""".lstrip(),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [compiler, "-O2", "-o", str(executable), str(source)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    executable.chmod(0o755)
    return Path(compiler).resolve()


def _dependency_identities(
    executable: Path,
) -> tuple[installer.BuildDependencyIdentity, ...]:
    digest = _sha256(executable)
    constraints = {
        **dict(installer.SOUFFLE_BUILD_DEPENDENCIES),
        "cmake_build_executor": ">=3.8",
        "cxx_compiler": "C++17",
    }
    return tuple(
        installer.BuildDependencyIdentity(
            name=name,
            constraint=constraint,
            version="99.1",
            resolver_kind="unit-test-native-fixture",
            executable=str(executable),
            executable_sha256=digest,
            probe_argv=(str(executable), "--version"),
        )
        for name, constraint in sorted(constraints.items())
    )


def _rewrite_manifest(path: Path, payload: dict[str, Any]) -> None:
    payload.pop("identity_manifest_sha256", None)
    payload["identity_manifest_sha256"] = installer._canonical_json_sha256(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _native_install_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, dict[str, str]]:
    install_root = (tmp_path / "managed").resolve()
    pin = dict(installer.DEFAULT_PINS[installer.TOOL_SOUFFLE])
    version_root = (
        install_root
        / "authorization-vendor"
        / installer.TOOL_SOUFFLE
        / pin["version"]
    )
    executable = version_root / "bin/souffle"
    dependency_executable = _compile_native_souffle(executable)
    binary_format, machine = installer._assert_native_binary_for_platform(
        executable,
        installer._detect_platform(),
    )

    archive = installer._source_archive_install_path(version_root, pin["version"])
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"pinned-source-archive-fixture")
    source_sha256 = _sha256(archive)
    pin["sha256"] = source_sha256

    lock_path = (tmp_path / "formal-verification.lock.json").resolve()
    lock_path.write_text('{"fixture":true}\n', encoding="utf-8")
    lock_sha256 = _sha256(lock_path)
    pin_contract_sha256 = hashlib.sha256(b"pin-contract").hexdigest()
    contract = {
        "build_dependencies": dict(installer.SOUFFLE_BUILD_DEPENDENCIES),
        "deployment_lock_path": lock_path,
        "deployment_lock_sha256": lock_sha256,
        "pin": pin,
        "pin_contract": {"fixture": True},
        "pin_contract_sha256": pin_contract_sha256,
        "source_archive_sha256": source_sha256,
        "source_archive_url": installer.SOUFFLE_SOURCE_ARCHIVE_URL,
    }
    monkeypatch.setattr(
        installer,
        "_validated_vendor_souffle_contract",
        lambda **_kwargs: contract,
    )

    dependencies = _dependency_identities(dependency_executable)
    dependency_map = installer._build_dependency_identity_map(dependencies)
    build_contract = {
        "artifact_kind": "native_compiled_executable",
        "build_dependency_identities": dependency_map,
        "dependency_package_set_sha256": "",
        "dependency_packages": {},
        "dependency_prefix": "",
        "dependency_prefix_artifacts": {},
        "package_metadata_tool": {},
        "pin_contract_sha256": pin_contract_sha256,
        "schema_version": installer.SOUFFLE_NATIVE_BUILD_SCHEMA,
        "source_archive_sha256": source_sha256,
    }
    manifest = version_root / "identity.json"
    payload: dict[str, Any] = {
        "artifact_kind": "native_compiled_executable",
        "artifact_sha256": _sha256(executable),
        "artifact_size_bytes": executable.stat().st_size,
        "authority_ceiling": "none",
        "build_contract": build_contract,
        "build_contract_sha256": installer._canonical_json_sha256(build_contract),
        "build_dependencies": dict(installer.SOUFFLE_BUILD_DEPENDENCIES),
        "build_dependency_identities": dependency_map,
        "dependency_package_set_sha256": "",
        "dependency_packages": {},
        "dependency_prefix": "",
        "deployment_lock_path": str(lock_path),
        "deployment_lock_sha256": lock_sha256,
        "executable": str(executable),
        "identity_kind": pin["identity_kind"],
        "install_root": str(install_root),
        "interface": installer.VENDOR_INTERFACE,
        "is_hermetic_shadow": False,
        "is_vendor_build": True,
        "license": pin["license"],
        "native_binary_format": binary_format,
        "native_machine": machine,
        "package_metadata_tool": {},
        "pin_contract_sha256": pin_contract_sha256,
        "platform_id": installer._detect_platform(),
        "role": "shadow",
        "schema_version": installer.VENDOR_INSTALL_RECEIPT_SCHEMA,
        "source": pin["source"],
        "source_archive_path": str(archive),
        "source_archive_sha256": source_sha256,
        "source_archive_url": installer.SOUFFLE_SOURCE_ARCHIVE_URL,
        "tool_id": installer.TOOL_SOUFFLE,
        "version": pin["version"],
    }
    _rewrite_manifest(manifest, payload)
    return install_root, executable, manifest, pin


def test_native_vendor_identity_binds_archive_dependencies_and_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, executable, _, pin = _native_install_fixture(
        tmp_path,
        monkeypatch,
    )

    identity = installer._identity_from_disk(
        installer.TOOL_SOUFFLE,
        install_root,
        pin,
        vendor=True,
    )

    assert identity is not None
    assert identity.native_binary_format in {"elf", "macho"}
    assert identity.artifact_sha256 == _sha256(executable)
    assert identity.source_archive_sha256 == _sha256(
        Path(identity.source_archive_path)
    )
    assert {item.name for item in identity.build_dependency_identities} == (
        set(installer.SOUFFLE_BUILD_DEPENDENCIES)
        | {"cxx_compiler", "cmake_build_executor"}
    )
    assert all(item.binding_sha256 for item in identity.build_dependency_identities)


def test_python_shim_cannot_claim_native_vendor_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, executable, manifest, pin = _native_install_fixture(
        tmp_path,
        monkeypatch,
    )
    executable.write_text(
        "#!/usr/bin/env python3\nprint('Version: 2.4.1')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["artifact_sha256"] = _sha256(executable)
    payload["artifact_size_bytes"] = executable.stat().st_size
    _rewrite_manifest(manifest, payload)

    assert installer._native_binary_identity(executable) == ("", "")
    assert (
        installer._identity_from_disk(
            installer.TOOL_SOUFFLE,
            install_root,
            pin,
            vendor=True,
        )
        is None
    )
    with pytest.raises(
        installer.AuthorizationInstallerError,
        match="Python Soufflé shim",
    ):
        installer.build_shadow_shim_source(
            installer.TOOL_SOUFFLE,
            "2.4.1",
            identity_file=str(manifest),
            is_vendor_build=True,
        )


def test_native_vendor_identity_rejects_archive_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, _, _, pin = _native_install_fixture(tmp_path, monkeypatch)
    archive = (
        install_root
        / "authorization-vendor"
        / installer.TOOL_SOUFFLE
        / "2.4.1"
        / "source-archive"
        / "souffle-2.4.1.tar.gz"
    )
    archive.write_bytes(archive.read_bytes() + b"tampered")

    assert (
        installer._identity_from_disk(
            installer.TOOL_SOUFFLE,
            install_root,
            pin,
            vendor=True,
        )
        is None
    )


def test_native_vendor_identity_rejects_build_dependency_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_root, _, manifest, pin = _native_install_fixture(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    cmake = payload["build_dependency_identities"]["cmake"]
    cmake["executable_sha256"] = "0" * 64
    cmake["binding_sha256"] = installer._canonical_json_sha256(
        {
            key: value
            for key, value in cmake.items()
            if key != "binding_sha256"
        }
    )
    payload["build_contract"]["build_dependency_identities"]["cmake"] = dict(
        cmake
    )
    payload["build_contract_sha256"] = installer._canonical_json_sha256(
        payload["build_contract"]
    )
    _rewrite_manifest(manifest, payload)

    assert (
        installer._identity_from_disk(
            installer.TOOL_SOUFFLE,
            install_root,
            pin,
            vendor=True,
        )
        is None
    )


def _build_debian_package(
    package_dir: Path,
    *,
    package: str,
    version: str,
    architecture: str,
    payload: str,
) -> Path:
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        pytest.skip("dpkg-deb is required for retained package identity tests")
    build_root = package_dir / f"build-{package}"
    control_dir = build_root / "DEBIAN"
    control_dir.mkdir(parents=True)
    (control_dir / "control").write_text(
        "\n".join(
            [
                f"Package: {package}",
                f"Version: {version}",
                "Section: devel",
                "Priority: optional",
                f"Architecture: {architecture}",
                "Maintainer: unit-test@example.invalid",
                "Description: native Souffle dependency identity fixture",
                "",
            ]
        ),
        encoding="utf-8",
    )
    data = build_root / "usr/share" / package / "payload"
    data.parent.mkdir(parents=True)
    data.write_text(payload, encoding="utf-8")
    output = package_dir / f"{package}_{version}_{architecture}.deb"
    completed = subprocess.run(
        [dpkg_deb, "--build", str(build_root), str(output)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    shutil.rmtree(build_root)
    return output


def test_explicit_dependency_prefix_binds_retained_package_versions_and_hashes(
    tmp_path: Path,
) -> None:
    platform_id = installer._detect_platform()
    architecture = {
        "linux-aarch64": "arm64",
        "linux-x86_64": "amd64",
    }.get(platform_id)
    if architecture is None:
        pytest.skip("retained Debian dependency-prefix test requires Linux")

    prefix = tmp_path / "ubuntu-platform" / "root"
    library_dir = prefix / "usr/lib/test-linux-gnu"
    pkg_config = library_dir / "pkgconfig"
    pkg_config.mkdir(parents=True)
    (pkg_config / "libffi.pc").write_text(
        "Name: libffi\nVersion: 3.4.6\n",
        encoding="utf-8",
    )
    include = prefix / "usr/include"
    multiarch_include = include / "test-linux-gnu"
    multiarch_include.mkdir(parents=True)
    (multiarch_include / "ffi.h").write_bytes(b"ffi-header")
    (multiarch_include / "ffitarget.h").write_bytes(b"ffi-target-header")
    (include / "sqlite3.h").write_bytes(b"sqlite-header")
    (include / "sqlite3ext.h").write_bytes(b"sqlite-extension-header")
    (library_dir / "libffi.so").write_bytes(b"ffi-library")
    (library_dir / "libsqlite3.so").write_bytes(b"sqlite-library")
    mcpp = prefix / "usr/bin/mcpp"
    mcpp.parent.mkdir(parents=True)
    mcpp.write_bytes(b"native-mcpp-fixture")

    package_dir = prefix.parent / "packages"
    package_dir.mkdir()
    versions = {
        "libffi-dev": "3.4.6-1build1",
        "libffi8": "3.4.6-1build1",
        "libmcpp0": "2.7.2-5.1",
        "libsqlite3-0": "3.45.1-1ubuntu2.7",
        "libsqlite3-dev": "3.45.1-1ubuntu2.7",
        "mcpp": "2.7.2-5.1",
    }
    package_paths = {
        package: _build_debian_package(
            package_dir,
            package=package,
            version=version,
            architecture=architecture,
            payload="first",
        )
        for package, version in versions.items()
    }

    first = installer._dependency_prefix_contract(
        prefix,
        platform_id=platform_id,
    )

    assert first["dependency_prefix"] == str(prefix.resolve())
    assert set(first["dependency_packages"]) == set(versions)
    assert {
        package: identity["version"]
        for package, identity in first["dependency_packages"].items()
    } == versions
    assert all(
        identity["sha256"] == _sha256(package_paths[package])
        for package, identity in first["dependency_packages"].items()
    )
    assert first["dependency_package_set_sha256"]
    assert first["package_metadata_tool"]["executable_sha256"]

    _build_debian_package(
        package_dir,
        package="mcpp",
        version=versions["mcpp"],
        architecture=architecture,
        payload="second",
    )
    second = installer._dependency_prefix_contract(
        prefix,
        platform_id=platform_id,
    )
    assert (
        second["dependency_package_set_sha256"]
        != first["dependency_package_set_sha256"]
    )

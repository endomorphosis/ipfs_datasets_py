"""Explicit Hyper dependency choices must not silently resolve through PATH.

Only local fixture files are inspected. Version observations are synthetic;
no native compiler, installer, network, or shared resource pool is used.
"""
import hashlib
import os
from pathlib import Path
import subprocess
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers.install_control import installation_scope
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler


@pytest.fixture(autouse=True)
def controlled_boundary(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dependency fixture attempted native execution, download, or shared admission")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(hp, "urlopen", forbidden)
    monkeypatch.setattr(hp, "_capture_dependency_version", forbidden)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", forbidden)
    with installation_scope(operation_timeout_ms=2000):
        yield


def executable(path, body=b"controlled executable identity\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(0o755)
    return path


def resolve(roots, name="dotnet", candidates=("dotnet",)):
    return hp._executable_from_dependency_roots(name, candidates, roots)


@pytest.mark.parametrize("layout", ["root", "bin", "sbin", "file", "alias-file"])
def test_explicit_sdk_layouts_resolve_the_actual_executable(tmp_path, layout):
    root = tmp_path / "sdk"
    path = executable(root / ({"bin": "bin/dotnet", "sbin": "sbin/dotnet"}.get(layout, "dotnet")))
    key = "dotnet" if layout == "file" else "dotnet-sdk"
    value = path if layout in {"file", "alias-file"} else root
    assert resolve(MappingProxyType({key: value})) == str(path.resolve())


def test_exact_file_key_preserves_custom_executable_basename(tmp_path):
    path = executable(tmp_path / "reviewed-sdk-host")
    assert resolve({"dotnet": path}) == str(path)


@pytest.mark.parametrize("kind", ["file", "root", "child", "alias-name"])
def test_valid_symlinks_bind_to_the_real_executable(tmp_path, kind):
    target = executable(tmp_path / "real" / "dotnet")
    if kind == "root":
        supplied = tmp_path / "sdk-link"; supplied.symlink_to(target.parent, target_is_directory=True)
    elif kind == "child":
        supplied = tmp_path / "sdk"; supplied.mkdir()
        (supplied / "dotnet").symlink_to(target)
    else:
        supplied = tmp_path / ("dotnet" if kind == "alias-name" else "custom-host-link")
        supplied.symlink_to(target)
    key = "dotnet-sdk" if kind != "file" else "dotnet"
    assert resolve({key: supplied}) == str(target)


@pytest.mark.parametrize("kind", ["missing", "empty-directory", "nonexecutable", "fifo", "broken-link", "cyclic-link"])
def test_invalid_explicit_choice_never_falls_back_to_path_or_lower_alias(monkeypatch, tmp_path, kind):
    supplied = tmp_path / "explicit"
    if kind == "empty-directory":
        supplied.mkdir()
    elif kind == "nonexecutable":
        supplied.write_bytes(b"not executable"); supplied.chmod(0o644)
    elif kind == "fifo":
        os.mkfifo(supplied)
    elif kind == "broken-link":
        supplied.symlink_to(tmp_path / "missing-target")
    elif kind == "cyclic-link":
        supplied.symlink_to(supplied)
    valid_alias = executable(tmp_path / "fallback-sdk" / "dotnet")
    monkeypatch.setattr(hp.shutil, "which", lambda *a, **k: pytest.fail("explicit root reached PATH"))
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER,
            dependency_roots={"dotnet": supplied, "dotnet-sdk": valid_alias.parent})
    assert error.value.block_reasons == ("invalid_dependency_root:dotnet",)


def test_nonexecutable_directory_candidate_is_not_selected(tmp_path):
    root = tmp_path / "sdk"; root.mkdir()
    (root / "dotnet").write_bytes(b"not executable")
    (root / "dotnet").chmod(0o644)
    valid = executable(root / "bin" / "dotnet")
    assert resolve({"dotnet-sdk": root}) == str(valid)


def test_directory_named_like_executable_is_not_an_executable(tmp_path):
    (tmp_path / "sdk" / "dotnet").mkdir(parents=True)
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="regular executable"):
        resolve({"dotnet-sdk": tmp_path / "sdk"})


def test_shared_spot_alias_cannot_reuse_one_program_for_two_dependencies(tmp_path):
    autfilt = executable(tmp_path / "autfilt")
    assert resolve({"spot": autfilt}, "autfilt", ("autfilt",)) == str(autfilt)
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        resolve({"spot": autfilt}, "ltl2tgba", ("ltl2tgba",))
    assert error.value.block_reasons == ("invalid_dependency_root:ltl2tgba",)


def test_exact_dependency_key_takes_priority_without_mutating_mapping(tmp_path):
    selected = executable(tmp_path / "selected")
    alias = executable(tmp_path / "alias" / "dotnet")
    roots = {"dotnet": selected, "dotnet-sdk": alias.parent}
    original = dict(roots)
    assert resolve(roots) == str(selected)
    assert roots == original


def test_candidate_name_key_and_exact_dependency_key_priority(tmp_path):
    first = executable(tmp_path / "configured-zlib-query")
    second = executable(tmp_path / "pkg-config")
    assert resolve({"zlib": first, "pkg-config": second}, "zlib", ("pkg-config",)) == str(first)
    assert resolve({"pkg-config": second}, "zlib", ("pkg-config",)) == str(second)


@pytest.mark.parametrize("roots", [False, [], "root", {1: "/tmp"}, {"": "/tmp"},
    {" dotnet": "/tmp"}, {"dotnet": None}, {"dotnet": True}, {"dotnet": object()},
    {"dotnet": ""}, {"dotnet": " /tmp"}, {"dotnet": "/tmp\x00path"},
    {"dotnet": "\ud800"}, {"dotnet": "x" * 4097},
    {str(i): "/tmp" for i in range(33)}])
def test_malformed_mapping_refused_before_resolution_or_probe(monkeypatch, roots):
    monkeypatch.setattr(hp.shutil, "which", lambda *a, **k: pytest.fail("invalid mapping reached PATH"))
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER, dependency_roots=roots)
    assert error.value.block_reasons == ("invalid_dependency_roots",)


def test_all_explicit_paths_are_preflighted_before_any_version_probe(monkeypatch, tmp_path):
    dotnet = executable(tmp_path / "dotnet")
    monkeypatch.setattr(hp.shutil, "which", lambda *a, **k: pytest.fail("invalid explicit path reached PATH"))
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER,
            dependency_roots={"dotnet": dotnet, "spot": tmp_path / "missing-spot"})
    assert error.value.block_reasons == ("invalid_dependency_root:autfilt",)


@pytest.mark.parametrize("configuration", [None, {}, {"unrelated-provenance": "/unselected/path"}])
def test_implicit_path_selection_remains_available_and_hash_bound(monkeypatch, tmp_path, configuration):
    tools = {name: executable(tmp_path / name, name.encode()) for name in ("dotnet", "autfilt", "ltl2tgba")}
    observations = []
    monkeypatch.setattr(hp.shutil, "which", lambda name: str(tools[name]))
    def observe(path, args, **kwargs):
        observations.append((path, tuple(args)))
        return "8.0.300" if Path(path).name == "dotnet" else "Spot 2.12"
    monkeypatch.setattr(hp, "_capture_dependency_version", observe)
    identities = hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER, dependency_roots=configuration)
    assert len(observations) == len(identities) == 3
    for identity in identities:
        assert identity.executable == str(tools[identity.name])
        assert identity.executable_sha256 == hashlib.sha256(tools[identity.name].read_bytes()).hexdigest()


def test_explicit_symlink_resolution_is_the_identity_hashed_and_probed(monkeypatch, tmp_path):
    tools = {name: executable(tmp_path / "real" / name, name.encode()) for name in ("dotnet", "autfilt", "ltl2tgba")}
    sdk = tmp_path / "sdk"; sdk.symlink_to(tools["dotnet"].parent, target_is_directory=True)
    spot = tmp_path / "spot"; spot.mkdir()
    for name in ("autfilt", "ltl2tgba"):
        (spot / name).symlink_to(tools[name])
    observations = []
    def observe(path, args, **kwargs):
        observations.append(path)
        return "8.0.300" if Path(path).name == "dotnet" else "Spot 2.12"
    monkeypatch.setattr(hp, "_capture_dependency_version", observe)
    monkeypatch.setattr(hp.shutil, "which", lambda *a, **k: pytest.fail("explicit choices reached PATH"))
    identities = hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER,
        dependency_roots=MappingProxyType({"dotnet-sdk": sdk, "spot": spot}))
    assert set(observations) == {str(path) for path in tools.values()}
    assert {item.executable for item in identities} == set(observations)


def test_explicit_executable_with_wrong_version_remains_refused_without_path_retry(monkeypatch, tmp_path):
    tools = {name: executable(tmp_path / name) for name in ("dotnet", "autfilt", "ltl2tgba")}
    monkeypatch.setattr(hp.shutil, "which", lambda *a, **k: pytest.fail("version mismatch retried PATH"))
    monkeypatch.setattr(hp, "_capture_dependency_version",
        lambda path, args, **kwargs: "7.0.100" if Path(path).name == "dotnet" else "Spot 2.12")
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        hp._resolve_vendor_dependencies(hp.TOOL_AUTOHYPER, dependency_roots=tools)
    assert error.value.block_reasons == ("dependency_version_mismatch:dotnet",)

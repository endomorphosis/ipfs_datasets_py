"""Local setup plans and controlled archive preparation; no host execution."""
from dataclasses import replace
from pathlib import Path
import hashlib
import io
import os
import subprocess
import threading

import pytest

from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers import hyperproperty_setup as setup
from ipfs_datasets_py.logic.backends.installers.install_control import HyperInstallLimits
from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler


@pytest.fixture(autouse=True)
def inert_boundary(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("setup test attempted native, shared admission or uncontrolled download")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)
    monkeypatch.setattr(hp, "_capture_dependency_version", denied)
    monkeypatch.setattr(hp, "urlopen", denied)
    monkeypatch.setattr(hp, "_safe_extract_source_archive", denied)
    monkeypatch.setattr(hp, "_run_build_command", denied)
    monkeypatch.setattr(hp.shutil, "which", lambda *args, **kwargs: None)
    monkeypatch.setattr(hp, "_detect_platform", lambda: hp.LINUX_AARCH64)


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture executable, never run\n")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("tool", hp.EXTERNAL_TOOLS)
def test_plan_and_default_prepare_are_inert_and_detached(tmp_path, tool):
    root = tmp_path / "uncreated"
    first = setup.plan_hyperproperty_setup(tool, install_root=root)
    second = setup.prepare_hyperproperty_dependencies(tool, install_root=root)
    assert first == second and not root.exists()
    assert first["validation_required"] and not first["installed"] and not first["native_probes_run"]
    assert not first["bootstrap_performed"] and first["blockers"]
    first["blockers"].clear(); first["dependency_roots"]["changed"] = "not shared"
    assert second["blockers"] and "changed" not in second["dependency_roots"]


def test_configured_root_uses_existing_public_resolver(monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    monkeypatch.setattr(lazy_installer, "configured_user_install_root", lambda: tmp_path)
    assert setup.plan_hyperproperty_setup("hyperltl")["managed_dependency_root"] == str(tmp_path)


def test_one_complete_ocaml_switch_is_used_without_mixing(tmp_path):
    complete = tmp_path / "opam/ipfs-datasets-coq"
    for name in ("ocamlc", "ocamlbuild", "ocamlfind", "menhir", "dune"):
        executable(complete / "bin" / name)
    executable(tmp_path / "opam/ipfs-datasets-proverif/bin/ocamlc")
    plan = setup.plan_hyperproperty_setup("hyperltl", install_root=tmp_path)
    assert plan["dependency_roots"] == {"opam-switch": str(complete)}
    rows = {row["name"]: row for row in plan["dependencies"]}
    assert all(rows[name]["candidate_found"] and not rows[name]["version_validated"]
               for name in ("ocamlc", "ocamlbuild", "ocamlfind", "menhir", "dune"))


def test_two_complete_ocaml_switches_need_explicit_selection(tmp_path):
    for switch in ("ipfs-datasets-coq", "ipfs-datasets-proverif"):
        for name in ("ocamlc", "ocamlbuild", "ocamlfind", "menhir", "dune"):
            executable(tmp_path / "opam" / switch / "bin" / name)
    plan = setup.plan_hyperproperty_setup("hyperltl", install_root=tmp_path)
    assert "ambiguous_managed_dependency:opam-switch" in plan["blockers"]
    assert "opam-switch" not in plan["dependency_roots"]


def test_autohyper_managed_sdk_spot_and_explicit_override(tmp_path):
    sdk = tmp_path / f"dotnet-sdk-{hp.AUTOHYPER_DOTNET_SDK}-linux-arm64"
    spot = tmp_path / "spot-2.12-linux-aarch64"
    executable(sdk / "dotnet")
    for name in ("autfilt", "ltl2tgba"):
        executable(spot / "bin" / name)
    plan = setup.plan_hyperproperty_setup("autohyper", install_root=tmp_path)
    assert not plan["blockers"] and all(row["candidate_found"] for row in plan["dependencies"])
    assert plan["status"] == "candidates_require_validation" and plan["installed"] is False
    custom = executable(tmp_path / "caller/chosen-host")
    plan = setup.plan_hyperproperty_setup("autohyper", install_root=tmp_path,
                                        dependency_roots={"dotnet": custom})
    assert next(row for row in plan["dependencies"] if row["name"] == "dotnet")["candidate_path"] == str(custom)


def test_invalid_explicit_root_is_reported_without_path_fallback(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(hp.shutil, "which", lambda name: calls.append(name))
    plan = setup.plan_hyperproperty_setup("autohyper", install_root=tmp_path,
                                        dependency_roots={"dotnet": tmp_path / "missing"})
    assert "invalid_dependency_root:dotnet" in plan["blockers"] and "dotnet" not in calls


def test_mchyper_coherent_active_compiler_db_and_missing_archives(tmp_path):
    base = tmp_path / "build-dependencies/mchyper"
    compiler = base / ".ghcup/ghc/9.4.7/bin"
    for name in ("ghc", "ghc-pkg"):
        target = executable(compiler / (name + "-9.4.7"))
        link = base / ".ghcup/bin" / name; link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    executable(base / ".ghcup/bin/cabal")
    executable(base / f"python-{hp.MCHYPER_PYTHON_VERSION}/bin/python2.7")
    executable(base / f"abc-{hp.MCHYPER_ABC_GIT_COMMIT}/abc")
    executable(base / f"aiger-{hp.MCHYPER_AIGER_VERSION}/aigtoaig")
    db = base / "cabal/store/ghc-9.4.7/package.db"; db.mkdir(parents=True)
    for name, version, _, _ in setup._archive_specs(hp):
        (tmp_path / "sources" / (f"Python-{version}" if name == "python" else f"{name}-{version}")).mkdir(parents=True)
    plan = setup.plan_hyperproperty_setup("mchyper", install_root=tmp_path)
    assert plan["dependency_roots"]["ghc-package-db"] == str(db)
    assert set(plan["blockers"]) == {"missing_dependency_archive:" + name for name in ("aiger", "abc", "python")}
    assert all(row["candidate_found"] for row in plan["dependencies"])


@pytest.mark.parametrize("tool", ["", "HyperLTL", "other", None, True])
def test_unknown_tool_is_rejected_without_mutation(tmp_path, tool):
    with pytest.raises(ValueError):
        setup.plan_hyperproperty_setup(tool, install_root=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("value", [1, "yes", None, [], {}])
def test_prepare_requires_exact_bool_authorization(tmp_path, value):
    with pytest.raises(ValueError, match="yes"):
        setup.prepare_hyperproperty_dependencies("mchyper", yes=value, install_root=tmp_path)


@pytest.mark.parametrize("field,value", [("install_root", "relative"), ("archive_cache_root", "relative"),
                                         ("install_root", " /bad"), ("archive_cache_root", "/bad\x00")])
def test_setup_paths_must_be_bounded_absolute(tmp_path, field, value):
    options = {"install_root": tmp_path, field: value}
    with pytest.raises(ValueError):
        setup.plan_hyperproperty_setup("mchyper", **options)


def test_unknown_dependency_root_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        setup.plan_hyperproperty_setup("autohyper", install_root=tmp_path,
                                      dependency_roots={"unreviewed": tmp_path})


def test_authorized_prepare_uses_only_exact_reviewed_archive_pins(monkeypatch, tmp_path):
    cache, calls = tmp_path / "owned-cache", []
    def download(url, path, digest):
        calls.append((url, path, digest))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"fixture, downloader separately tested")
        return path
    monkeypatch.setattr(hp, "_download_verified_archive", download)
    # This case checks exact reviewed pin dispatch, not hash implementation.
    # Separate integrity tests rehash controlled bytes with the real helper.
    expected = {setup._archive_filename(name, version): digest
                for name, version, _, digest in setup._archive_specs(hp)}
    monkeypatch.setattr(hp, "_sha256_file", lambda path, *, max_bytes: expected[path.name])
    result = setup.prepare_hyperproperty_dependencies("mchyper", yes=True,
        install_root=tmp_path / "managed", archive_cache_root=cache)
    assert calls == [(url, cache / setup._archive_filename(name, version), digest)
                     for name, version, url, digest in setup._archive_specs(hp)]
    assert len(result["verified_archives"]) == 3 and all(row["digest_verified"] for row in result["provenance_archives"])
    assert not result["installed"] and not result["native_probes_run"] and not result["bootstrap_performed"]
    assert not (tmp_path / "managed").exists()


@pytest.mark.parametrize("tool", ["hyperltl", "autohyper"])
def test_authorized_other_tools_do_not_download(monkeypatch, tmp_path, tool):
    monkeypatch.setattr(hp, "_download_verified_archive", lambda *args: pytest.fail("unexpected archive"))
    result = setup.prepare_hyperproperty_dependencies(tool, yes=True, install_root=tmp_path)
    assert result["verified_archives"] == []


@pytest.mark.parametrize("alias", ["archive", "source-archive"])
def test_explicit_archive_destination_is_authoritative(monkeypatch, tmp_path, alias):
    specs = tuple((name, version, url, hashlib.sha256(b"fixture").hexdigest())
                  for name, version, url, _ in setup._archive_specs(hp))
    monkeypatch.setattr(setup, "_archive_specs", lambda module: specs)
    targets = {name + "-" + alias: tmp_path / "explicit" / (name + ".archive")
               for name, _, _, _ in setup._archive_specs(hp)}
    original, calls = dict(targets), []
    def download(url, path, digest):
        calls.append(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"fixture")
        return path
    monkeypatch.setattr(hp, "_download_verified_archive", download)
    result = setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "managed",
        archive_cache_root=tmp_path / "unused-cache", dependency_roots=targets)
    assert calls == list(targets.values()) and targets == original
    assert [row["path"] for row in result["verified_archives"]] == [str(path) for path in calls]
    assert not (tmp_path / "unused-cache").exists()


def test_real_downloader_reuses_verified_archive_cache_without_connection(monkeypatch, tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    specifications = []
    for name, version, url, _ in setup._archive_specs(hp):
        content = (name + " controlled provenance bytes").encode()
        (cache / setup._archive_filename(name, version)).write_bytes(content)
        specifications.append((name, version, url, hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(setup, "_archive_specs", lambda module: tuple(specifications))
    result = setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "managed",
        archive_cache_root=cache)
    assert len(result["verified_archives"]) == 3
    assert all(row["digest_verified"] for row in result["provenance_archives"])


def test_explicit_archive_symlink_is_not_resolved_before_mutation_guard(tmp_path):
    outside = tmp_path / "outside"; outside.write_bytes(b"preserved")
    alias = tmp_path / "archive-link"; alias.symlink_to(outside)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "managed",
            dependency_roots={"aiger-source-archive": alias})
    assert outside.read_bytes() == b"preserved"


def test_prepare_precancel_stops_before_any_download(monkeypatch, tmp_path):
    signal = threading.Event(); signal.set()
    monkeypatch.setattr(hp, "_download_verified_archive", lambda *args: pytest.fail("download after stop"))
    with pytest.raises(ProofOperationCancelled):
        setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "absent", cancellation=signal)
    assert not (tmp_path / "absent").exists()


def test_prepare_stop_between_archives_never_returns_verified_plan(monkeypatch, tmp_path):
    signal, calls = threading.Event(), []
    def download(url, path, digest):
        calls.append(url); signal.set(); return path
    monkeypatch.setattr(hp, "_download_verified_archive", download)
    with pytest.raises(ProofOperationCancelled):
        setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path, cancellation=signal)
    assert len(calls) == 1


def test_real_bounded_downloader_refuses_corrupt_official_pin_without_replacement(monkeypatch, tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    target = cache / f"aiger-{hp.MCHYPER_AIGER_VERSION}.tar.gz"; target.write_bytes(b"previous invalid candidate")
    class Response(io.BytesIO):
        headers = {"Content-Length": "3"}
        def geturl(self): return hp.MCHYPER_AIGER_SOURCE_ARCHIVE_URL
    calls = []
    def open_response(request, **kwargs):
        calls.append(request.full_url); return Response(b"bad")
    monkeypatch.setattr(hp, "urlopen", open_response)
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "managed",
            archive_cache_root=cache, limits=replace(HyperInstallLimits(), max_download_bytes=1024))
    assert error.value.block_reasons == ("source_archive_digest_mismatch",)
    assert calls == [hp.MCHYPER_AIGER_SOURCE_ARCHIVE_URL]
    assert target.read_bytes() == b"previous invalid candidate" and set(cache.iterdir()) == {target}


def test_poisoned_archive_cache_symlink_is_not_followed(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    link = tmp_path / "cache-link"; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        setup.prepare_hyperproperty_dependencies("mchyper", yes=True, install_root=tmp_path / "managed", archive_cache_root=link)
    assert not list(outside.iterdir())

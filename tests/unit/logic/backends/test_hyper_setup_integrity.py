"""Setup evidence is a bounded final observation, never a cache immutability claim.

Fixtures use real local file hashes and controlled archive bytes. They never
connect to a server, launch a tool, install an engine or access a shared pool.
"""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers import hyperproperty_setup as setup
from ipfs_datasets_py.logic.backends.installers.install_control import HyperInstallLimits
from ipfs_datasets_py.logic.backends.smt import operation_budget
from ipfs_datasets_py.logic.backends.smt.operation_budget import (
    ProofOperationCancelled, ProofOperationTimeout,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler


@pytest.fixture(autouse=True)
def no_host_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("setup integrity fixture attempted native, network or shared resources")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)
    monkeypatch.setattr(hp, "urlopen", denied)
    monkeypatch.setattr(hp, "_capture_dependency_version", denied)
    monkeypatch.setattr(hp, "_safe_extract_source_archive", denied)
    monkeypatch.setattr(hp, "_run_build_command", denied)
    monkeypatch.setattr(hp.shutil, "which", lambda *args, **kwargs: None)
    monkeypatch.setattr(hp, "_detect_platform", lambda: hp.LINUX_X86_64)


@pytest.fixture
def archives(monkeypatch, tmp_path):
    original = setup._archive_specs(hp)
    bodies = {name: (name + " exact controlled archive bytes\n").encode()
              for name, _, _, _ in original}
    specs = tuple((name, version, url, hashlib.sha256(bodies[name]).hexdigest())
                  for name, version, url, _ in original)
    monkeypatch.setattr(setup, "_archive_specs", lambda module: specs)
    paths = {name: tmp_path / "cache" / setup._archive_filename(name, version)
             for name, version, _, _ in specs}
    def seed():
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bodies[name])
    def prepare(**options):
        return setup.prepare_hyperproperty_dependencies("mchyper", **{
            "yes": True, "install_root": tmp_path / "managed",
            "archive_cache_root": tmp_path / "cache", **options})
    return SimpleNamespace(specs=specs, bodies=bodies, paths=paths, seed=seed, prepare=prepare)


@pytest.mark.parametrize("shape", ["same", "lexical-alias", "hardlink", "ancestor", "descendant"])
def test_conflicting_destinations_refuse_before_any_download(monkeypatch, tmp_path, archives, shape):
    first = tmp_path / "chosen" / "one.archive"
    second = first
    if shape == "lexical-alias":
        second = first.parent / "unused" / ".." / first.name
    elif shape == "hardlink":
        first.parent.mkdir(); first.write_bytes(b"preserved")
        second = first.with_name("linked.archive"); os.link(first, second)
    elif shape == "ancestor":
        second = first / "child.archive"
    elif shape == "descendant":
        second = first.parent; first = second / "child.archive"
    monkeypatch.setattr(hp, "_download_verified_archive",
                        lambda *args: pytest.fail("known collision reached downloader"))
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        archives.prepare(dependency_roots={"aiger-archive": first, "abc-source-archive": second})
    assert error.value.block_reasons == ("source_archive_destination_conflict",)
    assert not (tmp_path / "cache").exists() and not (tmp_path / "managed").exists()
    if shape == "hardlink":
        assert first.read_bytes() == second.read_bytes() == b"preserved"
        assert set(first.parent.iterdir()) == {first, second}
    else:
        assert not first.exists() and not second.exists()


@pytest.mark.parametrize("shape", ["symlink", "parent-symlink", "directory", "fifo", "parent-file"])
def test_invalid_last_destination_prevents_earlier_mutation(monkeypatch, tmp_path, archives, shape):
    target = tmp_path / "last.archive"
    outside = tmp_path / "outside"; outside.mkdir()
    if shape == "symlink":
        (outside / "kept").write_bytes(b"preserved"); target.symlink_to(outside / "kept")
    elif shape == "parent-symlink":
        link = tmp_path / "link"; link.symlink_to(outside, target_is_directory=True)
        target = link / "last.archive"
    elif shape == "directory":
        target.mkdir()
    elif shape == "fifo":
        os.mkfifo(target)
    else:
        target.write_bytes(b"preserved"); target = target / "last.archive"
    monkeypatch.setattr(hp, "_download_verified_archive",
                        lambda *args: pytest.fail("invalid final target reached downloader"))
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        archives.prepare(dependency_roots={"python-archive": target})
    assert not (tmp_path / "cache").exists() and not (tmp_path / "managed").exists()
    assert all(path.read_bytes() == b"preserved" for path in outside.iterdir())


def test_canonical_destination_precedes_ignored_alias_without_mutating_inputs(monkeypatch, tmp_path, archives):
    roots = {"aiger-archive": tmp_path / "chosen" / "aiger",
             "aiger-source-archive": archives.paths["abc"]}
    before = dict(roots); calls = []
    by_url = {url: archives.bodies[name] for name, _, url, _ in archives.specs}
    def controlled_download(url, path, digest):
        calls.append(path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(by_url[url]); return path
    monkeypatch.setattr(hp, "_download_verified_archive", controlled_download)
    result = archives.prepare(dependency_roots=roots)
    assert roots == before and calls == [roots["aiger-archive"], archives.paths["abc"], archives.paths["python"]]
    assert all(row["digest_verified"] for row in result["provenance_archives"])
    assert result["dependency_roots"]["aiger-archive"] == str(roots["aiger-archive"])
    assert result["dependency_roots"]["aiger-source-archive"] == str(roots["aiger-source-archive"])
    for row in result["verified_archives"]:
        assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_real_cached_hashes_are_revalidated_with_explicit_byte_limit(monkeypatch, archives):
    archives.seed(); calls = []; original = hp._sha256_file
    def observe(path, *, max_bytes=None):
        calls.append((path, max_bytes)); return original(path, max_bytes=max_bytes)
    monkeypatch.setattr(hp, "_sha256_file", observe)
    result = archives.prepare(limits=replace(HyperInstallLimits(), max_download_bytes=128))
    assert calls == [(path, 128) for path in archives.paths.values()] * 2
    assert all(row["digest_verified"] for row in result["provenance_archives"])
    assert not result["installed"] and not result["native_probes_run"] and not result["bootstrap_performed"]


@pytest.mark.parametrize("mutation", ["corrupt", "missing", "directory", "symlink", "oversized"])
def test_files_changed_after_download_never_return_verified_plan(monkeypatch, tmp_path, archives, mutation):
    archives.seed(); original = setup.plan_hyperproperty_setup
    def plan_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs); path = archives.paths["aiger"]
        path.unlink()
        if mutation == "corrupt": path.write_bytes(b"different")
        elif mutation == "directory": path.mkdir()
        elif mutation == "symlink":
            outside = tmp_path / "outside"; outside.write_bytes(archives.bodies["aiger"]); path.symlink_to(outside)
        elif mutation == "oversized": path.write_bytes(b"x" * 129)
        return result
    monkeypatch.setattr(setup, "plan_hyperproperty_setup", plan_then_mutate)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        archives.prepare(limits=replace(HyperInstallLimits(), max_download_bytes=128))


def test_later_download_overwriting_earlier_archive_is_detected(monkeypatch, archives):
    by_url = {url: (name, archives.bodies[name]) for name, _, url, _ in archives.specs}
    def download(url, path, digest):
        name, body = by_url[url]
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
        if name == "python": archives.paths["aiger"].write_bytes(b"later writer")
        return path
    monkeypatch.setattr(hp, "_download_verified_archive", download)
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        archives.prepare()
    assert error.value.block_reasons == ("source_archive_digest_mismatch",)


@pytest.mark.parametrize("replace_same_bytes", [False, True])
def test_earlier_file_changed_during_final_hash_pass_is_detected(monkeypatch, archives, replace_same_bytes):
    archives.seed(); original_hash = hp._sha256_file; original_plan = setup.plan_hyperproperty_setup
    final = False
    def planned(*args, **kwargs):
        nonlocal final
        result = original_plan(*args, **kwargs); final = True; return result
    def hash_then_change(path, *, max_bytes=None):
        digest = original_hash(path, max_bytes=max_bytes)
        if final and path == archives.paths["python"]:
            earlier = archives.paths["aiger"]
            if replace_same_bytes:
                temporary = earlier.with_suffix(".replacement")
                temporary.write_bytes(archives.bodies["aiger"]); temporary.replace(earlier)
            else:
                earlier.write_bytes(b"overwritten after its hash")
        return digest
    monkeypatch.setattr(setup, "plan_hyperproperty_setup", planned)
    monkeypatch.setattr(hp, "_sha256_file", hash_then_change)
    with pytest.raises(hp.HyperpropertyInstallBlocked) as error:
        archives.prepare()
    assert error.value.block_reasons == ("source_archive_changed",)


@pytest.mark.parametrize("phase", ["preflight", "downloads", "final-hash", "publication"])
def test_cancellation_never_publishes_verified_preparation(monkeypatch, archives, phase):
    archives.seed(); stop = threading.Event(); original_download = hp._download_verified_archive
    original_hash = hp._sha256_file; original_plan = setup.plan_hyperproperty_setup
    final = False; downloads = []
    if phase == "preflight": stop.set()
    def download(url, path, digest):
        result = original_download(url, path, digest); downloads.append(path)
        if phase == "downloads" and len(downloads) == 3: stop.set()
        return result
    def planned(*args, **kwargs):
        nonlocal final
        result = original_plan(*args, **kwargs); final = True; return result
    def hashed(path, *, max_bytes=None):
        result = original_hash(path, max_bytes=max_bytes)
        if final and (phase == "final-hash" or phase == "publication" and path == archives.paths["python"]):
            stop.set()
        return result
    monkeypatch.setattr(hp, "_download_verified_archive", download)
    monkeypatch.setattr(setup, "plan_hyperproperty_setup", planned)
    monkeypatch.setattr(hp, "_sha256_file", hashed)
    with pytest.raises(ProofOperationCancelled):
        archives.prepare(cancellation=stop)
    assert len(downloads) == (0 if phase == "preflight" else 3)
    assert operation_budget.current_proof_operation() is None


def test_download_and_final_verification_share_original_deadline(monkeypatch, archives):
    archives.seed(); clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(operation_budget, "time", SimpleNamespace(monotonic=lambda: clock.now))
    original_plan = setup.plan_hyperproperty_setup
    def late_plan(*args, **kwargs):
        result = original_plan(*args, **kwargs); clock.now += 0.101; return result
    monkeypatch.setattr(setup, "plan_hyperproperty_setup", late_plan)
    with pytest.raises(ProofOperationTimeout):
        archives.prepare(operation_timeout_ms=100)
    assert operation_budget.current_proof_operation() is None


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture, never executed\n"); path.chmod(0o755)
    return path


@pytest.mark.parametrize("alias", ["ghcup", "ghcup-bin"])
def test_explicit_ghcup_group_overrides_discovered_managed_group(tmp_path, alias):
    managed = tmp_path / "managed"; discovered = managed / "build-dependencies/mchyper/.ghcup"
    explicit = tmp_path / "chosen-bin"
    for name in ("ghc", "ghc-pkg", "cabal"):
        _executable(discovered / "bin" / name); _executable(explicit / name)
    plan = setup.plan_hyperproperty_setup("mchyper", install_root=managed, dependency_roots={alias: explicit})
    rows = {row["name"]: row for row in plan["dependencies"]}
    for name in ("ghc", "ghc-pkg", "cabal"):
        assert rows[name]["candidate_path"] == str(explicit / name)
        assert rows[name]["source"] == "dependency_roots" and not rows[name]["version_validated"]
    assert plan["dependency_roots"][alias] == str(explicit)
    if alias == "ghcup-bin": assert "ghcup" not in plan["dependency_roots"]


def test_invalid_explicit_ghcup_alias_cannot_be_masked_by_discovery_or_path(monkeypatch, tmp_path):
    root = tmp_path / "managed"
    for name in ("ghc", "ghc-pkg", "cabal"):
        _executable(root / "build-dependencies/mchyper/.ghcup/bin" / name)
    lookups = []
    monkeypatch.setattr(hp.shutil, "which", lambda name: lookups.append(name))
    plan = setup.plan_hyperproperty_setup("mchyper", install_root=root,
                                        dependency_roots={"ghcup-bin": tmp_path / "missing"})
    assert "ghcup" not in plan["dependency_roots"]
    for name in ("ghc", "ghc-pkg", "cabal"):
        assert "invalid_dependency_root:" + name in plan["blockers"]
        assert name not in lookups
        assert not next(row for row in plan["dependencies"] if row["name"] == name)["candidate_found"]


def test_explicit_canonical_ghcup_keeps_precedence_over_alias(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for name in ("ghc", "ghc-pkg", "cabal"):
        _executable(first / name); _executable(second / name)
    plan = setup.plan_hyperproperty_setup("mchyper", install_root=tmp_path / "managed",
                                        dependency_roots={"ghcup": first, "ghcup-bin": second})
    rows = {row["name"]: row for row in plan["dependencies"]}
    assert all(rows[name]["candidate_path"] == str(first / name) for name in ("ghc", "ghc-pkg", "cabal"))

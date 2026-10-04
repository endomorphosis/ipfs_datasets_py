"""Authenticated SDK archive fixtures only; no native tools or network access."""
from dataclasses import replace
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends.installers import dotnet_sdk_archive as sdk
from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers.install_control import HyperInstallLimits, installation_scope
from ipfs_datasets_py.logic.backends.smt import operation_budget
from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled, ProofOperationTimeout
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler

URL = "https://builds.dotnet.microsoft.com/controlled-fixture.tar.gz"


@pytest.fixture(autouse=True)
def deny_host_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("SDK archive fixture attempted native, network or shared-pool work")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)
    monkeypatch.setattr(hp, "urlopen", denied)
    monkeypatch.setattr(hp, "_capture_dependency_version", denied)
    monkeypatch.setattr(hp, "_run_build_command", denied)


def file(name, body=b"fixture", mode=0o644):
    return (name, body, mode, tarfile.REGTYPE, "")


def directory(name, mode=0o755):
    return (name, b"", mode, tarfile.DIRTYPE, "")


def raw_tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as bundle:
        for name, body, mode, kind, link in entries:
            member = tarfile.TarInfo(name); member.type = kind; member.mode = mode
            member.size = len(body); member.linkname = link
            bundle.addfile(member, io.BytesIO(body))
    return output.getvalue()


def archive(tmp_path, entries=None, *, compressed=None):
    entries = entries if entries is not None else [file("./dotnet", b"never executed", 0o755),
                                                   file("./sdk/8.0.300/core.dll", b"managed payload")]
    body = gzip.compress(raw_tar(entries), mtime=0) if compressed is None else compressed
    path = tmp_path / "sdk.tar.gz"; path.write_bytes(body)
    return path, hashlib.sha512(body).hexdigest()


def limits(**changes):
    return replace(HyperInstallLimits(), **changes)


def extract(tmp_path, entries=None, *, bounds=None, compressed=None):
    source, digest = archive(tmp_path, entries, compressed=compressed)
    target = tmp_path / "extracted"
    with installation_scope(limits=bounds):
        inventory = sdk.extract_sdk_archive(source, target, digest)
    return source, target, inventory


class Response(io.BytesIO):
    def __init__(self, body, *, url=URL, length=None):
        super().__init__(body); self.url = url
        self.headers = {"Content-Length": str(len(body) if length is None else length)}
    def geturl(self): return self.url


def test_rootless_archive_preserves_executable_modes_and_full_inventory(tmp_path):
    source, target, inventory = extract(tmp_path, [directory("./"), file("./dotnet", b"host", 0o4755),
        file("sdk/8.0.300/core.dll", b"core", 0o640), directory("sdk/", 0o2755), directory("sdk/8.0.300/")])
    assert set(inventory["entries"]) == {"dotnet", "sdk", "sdk/8.0.300", "sdk/8.0.300/core.dll"}
    assert inventory["schema"] == sdk.INVENTORY_SCHEMA
    assert inventory["archive_sha512"] == hashlib.sha512(source.read_bytes()).hexdigest()
    assert inventory["compressed_bytes"] == source.stat().st_size
    assert (inventory["files"], inventory["directories"], inventory["bytes"]) == (2, 2, 8)
    assert (target / "dotnet").stat().st_mode & 0o7777 == 0o755
    assert (target / "sdk").stat().st_mode & 0o7777 == 0o755
    assert (target / "sdk/8.0.300/core.dll").stat().st_mode & 0o777 == 0o640
    with installation_scope():
        audited = sdk.audit_sdk_tree(target, inventory)
    assert audited == {"verified": True, "tree_sha256": inventory["tree_sha256"], "files": 2, "directories": 2, "bytes": 8}
    assert json.loads(json.dumps(inventory)) == inventory


def test_digest_rejection_precedes_any_extracted_payload_write(tmp_path):
    source, digest = archive(tmp_path)
    target = tmp_path / "new-parent" / "sdk"
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="SHA-512"):
        sdk.extract_sdk_archive(source, target, "0" * 128)
    assert not target.parent.exists() and hashlib.sha512(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("value", [None, "", "a" * 64, "A" * 128, "g" * 128, True])
def test_invalid_pin_refused_before_filesystem_mutation(tmp_path, value):
    target = tmp_path / "absent" / "sdk.tar.gz"
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.download_sdk_archive(URL, target, value)
    assert not target.parent.exists()


def test_verified_download_is_atomic_and_reused_without_second_connection(monkeypatch, tmp_path):
    body = b"exact controlled compressed bytes"; expected = hashlib.sha512(body).hexdigest()
    target = tmp_path / "cache" / "sdk.tar.gz"; calls = []
    def open_response(request, **kwargs):
        assert not target.exists(); assert 0 < kwargs["timeout"] <= 5
        calls.append(request.full_url); return Response(body)
    monkeypatch.setattr(hp, "urlopen", open_response)
    assert sdk.download_sdk_archive(URL, target, expected) == target
    assert sdk.download_sdk_archive(URL, target, expected) == target
    assert calls == [URL] and target.read_bytes() == body and list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("fault", ["digest", "declared-short", "declared-long", "over-limit", "unsafe-redirect"])
def test_failed_transfer_preserves_previous_file_and_removes_partial(monkeypatch, tmp_path, fault):
    target = tmp_path / "sdk.tar.gz"; target.write_bytes(b"old cache")
    body = b"new controlled bytes"; expected = hashlib.sha512(body).hexdigest()
    if fault == "digest": expected = "0" * 128
    length = len(body) - 1 if fault == "declared-short" else len(body) + 1 if fault == "declared-long" else len(body)
    url = "http://example.org/unsafe" if fault == "unsafe-redirect" else URL
    monkeypatch.setattr(hp, "urlopen", lambda *args, **kwargs: Response(body, length=length, url=url))
    with installation_scope(limits=limits(max_download_bytes=8 if fault == "over-limit" else 128)):
        with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.download_sdk_archive(URL, target, expected)
    assert target.read_bytes() == b"old cache" and set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize("shape", ["target-symlink", "parent-symlink", "fifo", "directory"])
def test_unsafe_cache_paths_never_open_network_or_modify_outside(tmp_path, shape):
    outside = tmp_path / "outside"; outside.mkdir(); kept = outside / "kept"; kept.write_bytes(b"kept")
    target = tmp_path / "sdk.tar.gz"
    if shape == "target-symlink": target.symlink_to(kept)
    elif shape == "parent-symlink":
        link = tmp_path / "link"; link.symlink_to(outside, target_is_directory=True); target = link / "sdk.tar.gz"
    elif shape == "fifo": os.mkfifo(target)
    else: target.mkdir()
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.download_sdk_archive(URL, target, "0" * 128)
    assert kept.read_bytes() == b"kept" and list(outside.iterdir()) == [kept]


@pytest.mark.parametrize("phase", ["after SDK archive download read", "before SDK archive publication"])
def test_download_cancel_preserves_old_cache_and_cleans_partial(monkeypatch, tmp_path, phase):
    target = tmp_path / "sdk.tar.gz"; target.write_bytes(b"old")
    body = b"new bytes"; stop = threading.Event(); checkpoint = sdk.installation_checkpoint
    def controlled(point):
        if point == phase: stop.set()
        return checkpoint(point)
    monkeypatch.setattr(sdk, "installation_checkpoint", controlled)
    monkeypatch.setattr(hp, "urlopen", lambda *args, **kwargs: Response(body))
    with pytest.raises(ProofOperationCancelled):
        with installation_scope(cancellation=stop): sdk.download_sdk_archive(URL, target, hashlib.sha512(body).hexdigest())
    assert target.read_bytes() == b"old" and set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize("path", ["../escape", "/absolute", "/", "sdk/../../escape", "sdk//file", "././dotnet",
                                  "sdk\\escape", "C:/escape", "sdk/./file", "sdk/line\nfeed", "\udcffbad"])
def test_unsafe_archive_paths_are_refused_and_owned_tree_removed(tmp_path, path):
    entries = [directory(path)] if path == "/" else [file(path)]
    source, digest = archive(tmp_path, entries); destination = tmp_path / "sdk"
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, destination, digest)
    assert not destination.exists() and not (tmp_path / "escape").exists()


@pytest.mark.parametrize("entries", [
    [file("dotnet"), file("./dotnet")], [directory("sdk"), directory("sdk/")],
    [file("sdk"), file("sdk/core")], [file("sdk/core"), file("sdk")],
    [file("sdk"), directory("sdk")], [directory("."), directory("./")],
    [file(sdk.MANIFEST_NAME)],
])
def test_duplicate_alias_ancestor_and_reserved_paths_fail_closed(tmp_path, entries):
    source, digest = archive(tmp_path, entries)
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.GNUTYPE_SPARSE])
def test_links_and_special_objects_are_not_extracted(tmp_path, kind):
    source, digest = archive(tmp_path, [file("dotnet"), ("special", b"", 0o777, kind, "../outside")])
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists() and not (tmp_path / "outside").exists()


@pytest.mark.parametrize("change,entries", [
    ({"max_member_bytes": 4}, [file("dotnet", b"12345")]),
    ({"max_extract_bytes": 8}, [file("one", b"1234"), file("two", b"12345")]),
    ({"max_archive_members": 2}, [file("one"), file("two"), file("three")]),
    ({"max_archive_depth": 2}, [file("a/b/c")]),
    ({"max_path_bytes": 4}, [file("abcde")]),
])
def test_expansion_and_layout_limits_are_enforced(tmp_path, change, entries):
    source, digest = archive(tmp_path, entries)
    with installation_scope(limits=limits(**change)):
        with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


def test_exact_file_total_header_and_path_bounds_are_allowed(tmp_path):
    source, target, inventory = extract(tmp_path, [file("one", b"1234"), file("two", b"5678")],
        bounds=limits(max_member_bytes=4, max_extract_bytes=8, max_archive_members=2, max_path_bytes=3, max_archive_depth=1))
    assert inventory["bytes"] == 8 and inventory["files"] == 2 and (target / "two").read_bytes() == b"5678"


@pytest.mark.parametrize("fault", ["gzip-trailer", "gzip-crc", "missing-tar-eof", "nonzero-after-tar", "second-gzip-member", "malformed-later-header"])
def test_authenticated_but_malformed_compressed_stream_is_rejected(tmp_path, fault):
    raw = raw_tar([file("dotnet", b"host")]); compressed = gzip.compress(raw, mtime=0)
    if fault == "gzip-trailer": compressed = compressed[:-4]
    elif fault == "gzip-crc": compressed = compressed[:-8] + bytes([compressed[-8] ^ 1]) + compressed[-7:]
    elif fault == "missing-tar-eof": compressed = gzip.compress(raw[:1024], mtime=0)
    elif fault == "nonzero-after-tar": compressed = gzip.compress(raw + b"hidden payload", mtime=0)
    elif fault == "malformed-later-header": compressed = gzip.compress(raw[:1024] + b"x" * 512 + raw[1536:], mtime=0)
    else: compressed += gzip.compress(b"hidden payload", mtime=0)
    source, digest = archive(tmp_path, compressed=compressed)
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


def test_excessive_extended_metadata_refused_before_tarfile_allocation(tmp_path):
    source, digest = archive(tmp_path, [("pax", b"x" * 65_537, 0o644, tarfile.XHDTYPE, ""), file("dotnet")])
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="metadata"):
        sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


def test_compressed_archive_limit_precedes_extraction(tmp_path):
    source, digest = archive(tmp_path)
    with installation_scope(limits=limits(max_download_bytes=source.stat().st_size - 1)):
        with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


def test_zero_padding_cannot_bypass_expanded_stream_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(sdk, "_TOTAL_METADATA_BYTES", 32)
    raw = raw_tar([file("dotnet", b"host")]) + b"\x00" * 100_000
    source, digest = archive(tmp_path, compressed=gzip.compress(raw, mtime=0))
    with installation_scope(limits=limits(max_extract_bytes=64, max_archive_members=2)):
        with pytest.raises(hp.HyperpropertyInstallBlocked, match="stream limit"):
            sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists()


@pytest.mark.parametrize("phase", ["SDK archive header", "SDK archive member copy", "SDK archive trailer",
                                  "before SDK extracted inventory publication"])
def test_extract_cancellation_cleans_partial_even_after_restrictive_modes(monkeypatch, tmp_path, phase):
    source, digest = archive(tmp_path, [directory("sdk", 0), file("sdk/core", b"payload", 0), file("dotnet", b"host", 0o755)])
    stop = threading.Event(); actual = sdk.installation_checkpoint
    def checkpoint(point):
        if point == phase: stop.set()
        return actual(point)
    monkeypatch.setattr(sdk, "installation_checkpoint", checkpoint)
    with pytest.raises(ProofOperationCancelled):
        with installation_scope(cancellation=stop): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists() and source.is_file()
    assert operation_budget.current_proof_operation() is None


def test_extraction_does_not_reset_enclosing_deadline(monkeypatch, tmp_path):
    source, digest = archive(tmp_path); clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(operation_budget, "time", SimpleNamespace(monotonic=lambda: clock.now))
    actual = sdk.installation_checkpoint
    def checkpoint(point):
        if point == "SDK archive member copy": clock.now += .101
        return actual(point)
    monkeypatch.setattr(sdk, "installation_checkpoint", checkpoint)
    with pytest.raises(ProofOperationTimeout):
        with installation_scope(operation_timeout_ms=100): sdk.extract_sdk_archive(source, tmp_path / "sdk", digest)
    assert not (tmp_path / "sdk").exists() and operation_budget.current_proof_operation() is None


@pytest.mark.parametrize("change", ["modified-file", "missing-file", "extra-file", "mode", "symlink", "forged-manifest"])
def test_cached_tree_must_match_authenticated_inventory_not_local_manifest(tmp_path, change):
    source, target, inventory = extract(tmp_path)
    host = target / "dotnet"
    if change in {"modified-file", "forged-manifest"}: host.write_bytes(b"different host")
    elif change == "missing-file": host.unlink()
    elif change == "extra-file": (target / "extra").write_bytes(b"unexpected")
    elif change == "mode": host.chmod(0o644)
    else:
        outside = tmp_path / "outside"; outside.write_bytes(host.read_bytes()); host.unlink(); host.symlink_to(outside)
    if change == "forged-manifest":
        forged = json.loads(json.dumps(inventory)); forged["entries"]["dotnet"]["sha256"] = hashlib.sha256(host.read_bytes()).hexdigest()
        (target / sdk.MANIFEST_NAME).write_text(json.dumps(forged))
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.audit_sdk_tree(target, inventory)
    assert source.is_file() and target.is_dir()


def test_installer_manifest_is_only_ignored_at_exact_root_name(tmp_path):
    _, target, inventory = extract(tmp_path)
    (target / sdk.MANIFEST_NAME).write_text('{"untrusted":"metadata only"}')
    assert sdk.audit_sdk_tree(target, inventory)["verified"] is True
    (target / "sdk" / sdk.MANIFEST_NAME).write_text("{}")
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.audit_sdk_tree(target, inventory)


@pytest.mark.parametrize("shape", ["symlink", "fifo", "directory", "oversized"])
def test_ignored_root_manifest_still_requires_bounded_regular_file(tmp_path, shape):
    _, target, inventory = extract(tmp_path); manifest = target / sdk.MANIFEST_NAME
    if shape == "symlink": manifest.symlink_to(target / "dotnet")
    elif shape == "fifo": os.mkfifo(manifest)
    elif shape == "directory": manifest.mkdir()
    else: manifest.write_bytes(b"x" * 65_537)
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.audit_sdk_tree(target, inventory)


def test_final_audit_cancellation_withholds_result_without_deleting_installation(monkeypatch, tmp_path):
    _, target, inventory = extract(tmp_path); stop = threading.Event(); checkpoint = sdk.installation_checkpoint
    def controlled(point):
        if point == "before SDK tree audit publication": stop.set()
        return checkpoint(point)
    monkeypatch.setattr(sdk, "installation_checkpoint", controlled)
    with pytest.raises(ProofOperationCancelled):
        with installation_scope(cancellation=stop): sdk.audit_sdk_tree(target, inventory)
    assert (target / "dotnet").read_bytes() == b"never executed"
    assert operation_budget.current_proof_operation() is None


def test_earlier_hashed_file_changed_before_audit_publication_is_refused(monkeypatch, tmp_path):
    _, target, inventory = extract(tmp_path)
    actual = sdk._hash_stream
    calls = []
    def hash_then_change(stream, maximum, algorithm):
        result = actual(stream, maximum, algorithm); calls.append(stream.name)
        if len(calls) == inventory["files"]:
            # All byte hashes have completed; the final path observations
            # must still prevent publishing the earlier file's stale digest.
            (target / "dotnet").write_bytes(b"changed after hashing")
        return result
    monkeypatch.setattr(sdk, "_hash_stream", hash_then_change)
    with pytest.raises(hp.HyperpropertyInstallBlocked): sdk.audit_sdk_tree(target, inventory)
    assert len(calls) == inventory["files"] and target.is_dir()

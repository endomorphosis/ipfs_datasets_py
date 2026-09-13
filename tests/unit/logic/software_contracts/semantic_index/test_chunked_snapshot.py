"""Real small Git objects exercise the bounded large-population representation."""

from dataclasses import replace
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError, cid_for_byte_chunks, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index import chunked_snapshot as c
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    build_semantic_state, verify_semantic_state_bundle,
)


def git(root, *args, data=None):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        input=data, stderr=subprocess.DEVNULL).decode().strip()


def commit(root):
    git(root, "add", "-A")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "fixture")
    return dict(repository_id="fixture:chunked", expected_commit=git(root, "rev-parse", "HEAD"),
                expected_tree=git(root, "rev-parse", "HEAD^{tree}"))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "module.py").write_bytes(b"def add(a, b):\n    return a + b\n")
    return root, commit(root)


def test_chunk_source_cid_matches_existing_identity_including_empty_source():
    assert cid_for_byte_chunks([], max_chunk_bytes=2) == cid_for_bytes(b"")
    assert cid_for_byte_chunks([b"a", b"bc", b"", b"d"], max_chunk_bytes=2) == cid_for_bytes(b"abcd")
    with pytest.raises(ContentIdentityError, match="frame"):
        cid_for_byte_chunks([b"abc"], max_chunk_bytes=2)
    with pytest.raises(TypeError):
        cid_for_byte_chunks([bytearray(b"ab")], max_chunk_bytes=2)


def test_binary_and_oversized_code_are_fully_hashed_and_keep_exact_population(source, monkeypatch):
    root, _ = source
    binary = bytes(range(256)) * 512
    big_code = b"x = 1\n" * 22000
    (root / "coverage").mkdir()
    (root / "coverage/blob.bin").write_bytes(binary)
    (root / "copy.bin").write_bytes(binary)
    (root / "large.py").write_bytes(big_code)
    (root / "empty.bin").write_bytes(b"")
    request = commit(root)
    seen, frame_lengths = [], []
    actual = c._git_blob_frames

    def instrumented(path, oid, size, frame_bytes):
        seen.append(oid)
        for frame in actual(path, oid, size, frame_bytes):
            frame_lengths.append(len(frame))
            yield frame

    monkeypatch.setattr(c, "_git_blob_frames", instrumented)
    chunked = c.snapshot_chunked_repository(root, **request, limits=c.ChunkedSnapshotLimits(frame_bytes=4096))
    assert len(chunked.entries) == 5
    assert len(chunked.blobs) == len(seen) == len(set(seen)) == 4
    assert max(frame_lengths) <= 4096
    binary_manifest = next(blob for blob in chunked.blobs if blob.source_cid == cid_for_bytes(binary))
    assert binary_manifest.size_bytes == len(binary)
    assert len(binary_manifest.chunks) == 32
    root_cid, blocks = chunked.manifest_blocks()
    assert root_cid == chunked.snapshot_cid
    assert all(len(raw) <= c.MAX_FRAME_BYTES for raw in blocks.values())
    assert all(cid_for_structured(json.loads(raw)) == cid for cid, raw in blocks.items())
    assert not any(binary[:256].hex() in raw.decode() for raw in blocks.values())

    # Every blob is read again before any projection is returned. Large code
    # is content-verified but deliberately not represented as analyzed code.
    projected = c.project_chunked_repository(root, chunked, max_file_bytes=1024)
    assert len(seen) == 8
    assert projected.chunked_snapshot_cid == root_cid
    assert projected.unique_blob_bytes_verified == len(binary) + len(big_code) + (root / "module.py").stat().st_size
    assert projected.retained_source_bytes == (root / "module.py").stat().st_size
    entries = {entry.path: entry for entry in projected.snapshot.entries}
    for name, data in (("copy.bin", binary), ("coverage/blob.bin", binary), ("large.py", big_code)):
        assert entries[name].source_cid == cid_for_bytes(data)
        assert entries[name].captured_bytes is None
        assert entries[name].opaque_reason == "analysis_budget_exceeded"
    state = RepositoryScanner(repository_id=request["repository_id"]).scan_snapshot(
        projected.snapshot, {entry.source_key: entry.captured_bytes for entry in projected.snapshot.entries
                             if entry.captured_bytes is not None})
    assert any(symbol.module_path == "module.py" for symbol in state.symbols)
    assert not any(symbol.module_path == "large.py" for symbol in state.symbols)
    opaque = {artifact.path: artifact for artifact in state.artifacts if artifact.kind == "opaque"}
    assert opaque["large.py"].source_cid == cid_for_bytes(big_code)
    bundle = build_semantic_state(state)
    assert verify_semantic_state_bundle(bundle).root_cid == bundle.root.root_cid
    facts = [json.loads(raw) for raw in bundle.blocks.values()]
    assert any(fact.get("path") == "large.py" and fact.get("source_cid") == cid_for_bytes(big_code)
               and fact.get("artifact", {}).get("metadata", {}).get("opaque_reason") == "analysis_budget_exceeded"
               for fact in facts)


@pytest.mark.parametrize("changed", ["chunk", "source", "omitted_blob", "entry", "population"])
def test_tampered_chunk_and_population_claims_cannot_be_projected(source, changed):
    root, request = source
    chunked = c.snapshot_chunked_repository(root, **request, limits=c.ChunkedSnapshotLimits(frame_bytes=8))
    blob = chunked.blobs[0]
    if changed == "chunk":
        bad = replace(blob.chunks[0], source_cid=cid_for_bytes(b"tampered"))
        chunked = replace(chunked, blobs=(replace(blob, chunks=(bad, *blob.chunks[1:])),))
    elif changed == "source":
        chunked = replace(chunked, blobs=(replace(blob, source_cid=cid_for_bytes(b"tampered")),))
    elif changed == "omitted_blob":
        chunked = replace(chunked, blobs=())
    elif changed == "entry":
        chunked = replace(chunked, entries=())
    else:
        chunked = replace(chunked, population_cid=cid_for_bytes(b"tampered"))
    with pytest.raises(c.GitSnapshotError, match="manifest|population"):
        c.project_chunked_repository(root, chunked)


@pytest.mark.parametrize("limits,reason", [
    (c.ChunkedSnapshotLimits(max_stream_bytes=1), "streaming work"),
    (c.ChunkedSnapshotLimits(frame_bytes=1, max_chunks=1), "chunk reference"),
    (c.ChunkedSnapshotLimits(max_metadata_bytes=2000), "metadata budget"),
])
def test_stream_work_and_reference_budgets_refuse_before_content_reads(source, monkeypatch, limits, reason):
    root, request = source
    monkeypatch.setattr(c, "_git_blob_frames", lambda *args: pytest.fail("blob read beyond preflight budget"))
    with pytest.raises(c.SnapshotError, match=reason):
        c.snapshot_chunked_repository(root, **request, limits=limits)


def test_projection_retained_budget_cannot_silently_drop_normal_files(source, monkeypatch):
    root, request = source
    chunked = c.snapshot_chunked_repository(root, **request)
    monkeypatch.setattr(c, "_git_blob_frames", lambda *args: pytest.fail("unadmitted retained bytes read"))
    with pytest.raises(c.SnapshotError, match="retained source"):
        c.project_chunked_repository(root, chunked, max_total_bytes=1)
    with pytest.raises(c.SnapshotError, match="fixed retained"):
        c.project_chunked_repository(root, chunked, max_file_bytes=c.MAX_MATERIALIZED_FILE_BYTES + 1)
    with pytest.raises(c.SnapshotError, match="fixed frame"):
        c.ChunkedSnapshotLimits(frame_bytes=c.MAX_FRAME_BYTES + 1)


@pytest.mark.parametrize("mutation", ["truncated", "corrupt", "extra"])
def test_incomplete_or_wrong_git_content_never_produces_a_manifest(source, monkeypatch, mutation):
    root, request = source
    original = (root / "module.py").read_bytes()
    data = original[:-1] if mutation == "truncated" else original + b"!" if mutation == "extra" else b"!" * len(original)
    def altered(*args):
        yield data
    monkeypatch.setattr(c, "_git_blob_frames", altered)
    with pytest.raises(c.GitSnapshotError, match="recorded size|object identity"):
        c.snapshot_chunked_repository(root, **request)


def test_git_replacement_is_ignored_and_later_object_loss_fails_closed(source):
    root, request = source
    original = git(root, "rev-parse", "HEAD:module.py")
    other = git(root, "hash-object", "-w", "--stdin", data=b"evil = True\n")
    git(root, "replace", original, other)
    chunked = c.snapshot_chunked_repository(root, **request)
    assert chunked.blobs[0].source_cid == cid_for_bytes((root / "module.py").read_bytes())
    (root / ".git/objects" / original[:2] / original[2:]).unlink()
    with pytest.raises(c.GitSnapshotError):
        c.project_chunked_repository(root, chunked)


def test_symlink_blob_is_hashed_and_gitlink_remains_an_explicit_forest_boundary(source):
    root, request = source
    (root / "link.py").symlink_to("module.py")
    (root / "nested").mkdir()
    git(root, "update-index", "--add", "--cacheinfo", "160000", request["expected_commit"], "nested")
    request = commit(root)
    chunked = c.snapshot_chunked_repository(root, **request)
    projected = c.project_chunked_repository(root, chunked)
    entries = {entry.path: entry for entry in projected.snapshot.entries}
    assert entries["link.py"].source_cid == cid_for_bytes(b"module.py")
    assert entries["link.py"].opaque_reason == "symlink_or_nonregular"
    assert entries["nested"].source_cid is None
    assert entries["nested"].opaque_reason == "symlink_or_nonregular"
    assert len(chunked.entries) == 3 and len(chunked.blobs) == 2


def test_peak_retained_memory_does_not_follow_large_blob_size(source):
    import tracemalloc
    root, _ = source
    with (root / "large.bin").open("wb") as stream:
        for _ in range(768):
            stream.write(b"\x00\xff" * 4096)
    request = commit(root)
    cid_for_bytes(b"")
    cid_for_structured({})
    tracemalloc.start()
    try:
        snapshot = c.snapshot_chunked_repository(root, **request,
                                                limits=c.ChunkedSnapshotLimits(frame_bytes=65536))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sum(blob.size_bytes for blob in snapshot.blobs) > 6 * 1024 * 1024
    assert peak < 2 * 1024 * 1024


def test_inventory_pages_keep_metadata_frames_bounded(source, monkeypatch):
    root, _ = source
    for number in range(12):
        (root / (str(number) + "x" * 140 + ".py")).write_bytes(b"x = 1\n")
    request = commit(root)
    monkeypatch.setattr(c, "MAX_FRAME_BYTES", 2048)
    snapshot = c.snapshot_chunked_repository(root, **request,
                                            limits=c.ChunkedSnapshotLimits(frame_bytes=64))
    cid, blocks = snapshot.manifest_blocks()
    descriptor = json.loads(blocks[cid])
    assert len(descriptor["entry_pages"]) > 1
    entries = [entry for ref in descriptor["entry_pages"] for entry in json.loads(blocks[ref])["records"]]
    assert len(entries) == 13
    assert all(len(raw) <= 2048 for raw in blocks.values())


def test_stalled_blob_child_is_reaped_without_leaking_a_stream(source, monkeypatch):
    import signal
    import sys
    root, _ = source
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    monkeypatch.setattr(c.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(c, "GIT_COMMAND_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(c.GitCommandTimeout):
        list(c._git_blob_frames(root, "a" * 40, 1, 1))
    assert child.returncode == -signal.SIGKILL
    assert child.stdout.closed and child.stderr.closed


@pytest.mark.parametrize("phase", ["capture", "projection"])
def test_source_drift_during_content_stream_fails_before_return(source, monkeypatch, phase):
    root, request = source
    chunked = c.snapshot_chunked_repository(root, **request)
    real = c._hash_blob
    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        (root / "module.py").write_bytes(b"changed = True\n")
        return result
    monkeypatch.setattr(c, "_hash_blob", changed)
    with pytest.raises(c.GitSnapshotError, match="clean checkout"):
        if phase == "capture":
            c.snapshot_chunked_repository(root, **request)
        else:
            c.project_chunked_repository(root, chunked)


def test_frame_read_checks_the_whole_blob_before_returning_bounded_bytes(source, monkeypatch):
    root, request = source
    chunked = c.snapshot_chunked_repository(root, **request, limits=c.ChunkedSnapshotLimits(frame_bytes=8))
    blob = chunked.blobs[0]
    assert c.read_chunked_blob_frame(root, chunked, git_object_oid=blob.git_object_oid,
                                     chunk_index=1) == (root / "module.py").read_bytes()[8:16]
    bad_last = replace(blob.chunks[-1], source_cid=cid_for_bytes(b"bad trailing bytes"))
    tampered = replace(chunked, blobs=(replace(blob, chunks=(*blob.chunks[:-1], bad_last)),))
    with pytest.raises(c.GitSnapshotError, match="verify chunked manifest"):
        c.read_chunked_blob_frame(root, tampered, git_object_oid=blob.git_object_oid, chunk_index=0)
    monkeypatch.setattr(c, "_hash_blob", lambda *args, **kwargs: pytest.fail("read outside admitted frame"))
    with pytest.raises(c.GitSnapshotError, match="outside the committed population"):
        c.read_chunked_blob_frame(root, chunked, git_object_oid="a" * 40, chunk_index=0)
    with pytest.raises(c.SnapshotError, match="chunk_index"):
        c.read_chunked_blob_frame(root, chunked, git_object_oid=blob.git_object_oid, chunk_index=True)


def test_git_decoder_has_a_fixed_kernel_memory_bound(source, monkeypatch):
    import resource
    root, _ = source
    (root / "module.py").write_bytes(b"x = 1\n" * 10000)
    commit(root)
    oid = git(root, "rev-parse", "HEAD:module.py")
    real_popen, children = c.subprocess.Popen, []
    def start(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(c.subprocess, "Popen", start)
    frames = c._git_blob_frames(root, oid, 60000, 4096)
    try:
        assert len(next(frames)) == 4096
        assert resource.prlimit(children[0].pid, resource.RLIMIT_AS) == (
            c.MAX_GIT_DECODER_ADDRESS_BYTES, c.MAX_GIT_DECODER_ADDRESS_BYTES)
    finally:
        frames.close()
    assert children[0].returncode is not None


def test_real_packed_delta_objects_stream_under_decoder_bounds(source):
    import random
    root, _ = source
    base = random.Random(7).randbytes(65536)
    expected = {}
    for index in range(12):
        data = base[:32000] + bytes([index]) + base[32001:]
        path = root / f"packed-{index}.bin"
        path.write_bytes(data)
        expected[git(root, "hash-object", str(path))] = data
    request = commit(root)
    git(root, "repack", "-adf", "--window=20", "--depth=10")
    indexes = list((root / ".git/objects/pack").glob("*.idx"))
    assert len(indexes) == 1
    details = git(root, "verify-pack", "-v", str(indexes[0]))
    assert any(len(row.split()) == 7 and row.split()[1] == "blob" for row in details.splitlines())
    chunked = c.snapshot_chunked_repository(root, **request,
                                           limits=c.ChunkedSnapshotLimits(frame_bytes=4096))
    for blob in chunked.blobs:
        if blob.git_object_oid in expected:
            assert blob.source_cid == cid_for_bytes(expected[blob.git_object_oid])
    oid = next(iter(expected))
    assert c.read_chunked_blob_frame(root, chunked, git_object_oid=oid,
                                     chunk_index=2) == expected[oid][8192:12288]
    cid, blocks = chunked.manifest_blocks()
    assert json.loads(blocks[cid])["git_decoder_config"] == dict(c.GIT_DECODER_CONFIG)


def test_decoder_address_refusal_returns_no_verified_manifest(source, monkeypatch):
    root, request = source
    monkeypatch.setattr(c, "MAX_GIT_DECODER_ADDRESS_BYTES", 1024)
    with pytest.raises(c.GitBlobDecoderError) as refused:
        c.snapshot_chunked_repository(root, **request)
    assert refused.value.decoder_address_limit_bytes == 1024

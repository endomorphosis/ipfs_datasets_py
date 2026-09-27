"""Closed metadata DAGs preserve exact populations without oversized frames."""

from dataclasses import replace
import hashlib
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index import chunked_snapshot as c, paged_snapshot as p
from ipfs_datasets_py.logic.software_contracts.semantic_index.committed_snapshot import CommittedPopulationEntry
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry


def synthetic(count):
    data = b"x\n"
    oid = hashlib.sha1(b"blob 2\0" + data).hexdigest()
    source = cid_for_bytes(data)
    inventory = tuple(CommittedPopulationEntry(f"src/file_{i:05}.py".encode().hex(), "100644", "blob", oid, 2)
                      for i in range(count))
    population = {"schema": "ipfs-datasets.complete-committed-population@1", "repository_id": "fixture:paged",
                  "commit": "a" * 40, "tree": "b" * 40, "scope": "complete-committed", "exclusions": [],
                  "entries": [entry.to_dict() for entry in inventory]}
    chunked = c.ChunkedRepositorySnapshot("fixture:paged", "a" * 40, "b" * 40, cid_for_structured(population),
                                         inventory, (c.ChunkedBlob(oid, 2, source, (c.BlobChunk(0, 2, source),)),),
                                         c.ChunkedSnapshotLimits())
    entries = tuple(SnapshotEntry(entry.path, "opaque", 2, source, "analysis_budget_exceeded", entry.raw_path_hex,
                                  oid, "git-object", "clean", oid) for entry in inventory)
    snapshot = RepositorySnapshot("fixture:paged", entries, "git-clean", 1, 20000, "b" * 40, "a" * 40, ())
    return chunked, snapshot


def parse_chunked(root, blocks, chunked):
    return p.parse_chunked_snapshot_manifest(root, blocks, repository_id=chunked.repository_id,
                                             expected_commit=chunked.git_commit, expected_tree=chunked.git_tree,
                                             expected_population_cid=chunked.population_cid)


def parse_snapshot(root, blocks, evidence):
    return p.parse_paged_snapshot_evidence(root, blocks, expected_snapshot_cid=evidence.snapshot_cid,
                                           expected_source_manifest_cid=evidence.source_manifest_cid,
                                           repository_id=evidence.repository_id, expected_commit=evidence.git_commit,
                                           expected_tree=evidence.git_tree)


def rewrite(blocks, root, target, replacement):
    """An attacker rehashes every parent, so failures must enforce semantics too."""
    changed = {}
    def visit(cid):
        payload = replacement if cid == target else json.loads(blocks[cid])
        def transform(value):
            if type(value) is dict:
                return {key: transform(item) for key, item in value.items()}
            if type(value) is list:
                return [transform(item) for item in value]
            if type(value) is str and value in blocks:
                return visit(value)
            return value
        payload = transform(payload)
        new = cid_for_structured(payload)
        changed[new] = canonical_dag_json_bytes(payload)
        return new
    return visit(root), changed


def test_complete_15770_entry_metadata_population_fits_bounded_pages():
    chunked, snapshot = synthetic(15770)
    chunk_root, chunk_blocks = chunked.manifest_blocks()
    admitted = parse_chunked(chunk_root, chunk_blocks, chunked)
    assert admitted.entries == chunked.entries
    evidence = p.page_snapshot_evidence(snapshot, chunk_root)
    restored, verified = parse_snapshot(evidence.root_cid, evidence.blocks, evidence)
    assert len(restored.entries) == 15770
    assert restored.snapshot_cid == snapshot.snapshot_cid
    assert all(entry.captured_bytes is None for entry in restored.entries)
    assert verified.root_cid == evidence.root_cid
    pages = json.loads(evidence.blocks[evidence.root_cid])["entry_pages"]
    assert len(pages) > 1
    assert all(len(raw) <= c.MAX_FRAME_BYTES for raw in (*chunk_blocks.values(), *evidence.blocks.values()))
    artifact = verified.artifact()
    assert len(canonical_dag_json_bytes(artifact.to_dict())) < 4096
    assert "entries" not in artifact.metadata["snapshot"]
    assert artifact.metadata["snapshot"]["entry_count"] == 15770


@pytest.mark.parametrize("attack", ["omit", "duplicate", "reorder", "substitute", "count", "unknown", "mode_type"])
def test_chunk_population_pages_reject_rehashed_attacks(attack):
    chunked, _ = synthetic(5)
    root, blocks = chunked.manifest_blocks()
    descriptor = json.loads(blocks[root])
    target = descriptor["entry_pages"][0]
    page = json.loads(blocks[target])
    if attack == "omit":
        page["records"].pop()
    elif attack == "duplicate":
        page["records"][1] = page["records"][0]
    elif attack == "reorder":
        page["records"].reverse()
    elif attack == "substitute":
        page["records"][0]["git_object_oid"] = "0" * 40
    elif attack == "mode_type":
        page["records"][0]["git_mode"] = []
    elif attack == "count":
        target, page = root, descriptor
        page["entry_count"] += 1
    else:
        page["unknown"] = True
    forged_root, forged = rewrite(blocks, root, target, page)
    with pytest.raises(p.SnapshotError):
        parse_chunked(forged_root, forged, chunked)


@pytest.mark.parametrize("attack", ["omit_page", "duplicate_page", "reorder_pages", "substitute_entry", "count", "unknown"])
def test_snapshot_pages_reject_rehashed_attacks(attack):
    chunked, snapshot = synthetic(6)
    evidence = p.page_snapshot_evidence(snapshot, chunked.snapshot_cid, page_bytes=2048)
    root, blocks = evidence.root_cid, evidence.blocks
    descriptor = json.loads(blocks[root])
    assert len(descriptor["entry_pages"]) > 1
    target, payload = root, descriptor
    if attack == "omit_page":
        payload["entry_pages"].pop()
    elif attack == "duplicate_page":
        payload["entry_pages"][1] = payload["entry_pages"][0]
    elif attack == "reorder_pages":
        payload["entry_pages"].reverse()
    elif attack == "substitute_entry":
        target = descriptor["entry_pages"][0]
        payload = json.loads(blocks[target])
        payload["records"][0]["source_cid"] = cid_for_bytes(b"unverified")
    elif attack == "count":
        payload["entry_count"] += 1
    else:
        payload["unknown"] = True
    forged_root, forged = rewrite(blocks, root, target, payload)
    with pytest.raises(p.SnapshotError):
        parse_snapshot(forged_root, forged, evidence)


@pytest.mark.parametrize("kind", ["chunk", "snapshot"])
@pytest.mark.parametrize("attack", ["missing", "corrupt", "extra"])
def test_every_metadata_block_must_be_present_canonical_and_reachable(kind, attack):
    chunked, snapshot = synthetic(4)
    evidence = p.page_snapshot_evidence(snapshot, chunked.snapshot_cid)
    root, original = chunked.manifest_blocks() if kind == "chunk" else (evidence.root_cid, evidence.blocks)
    blocks = dict(original)
    leaf = next(cid for cid in blocks if cid != root)
    if attack == "missing":
        del blocks[leaf]
    elif attack == "corrupt":
        blocks[leaf] = blocks[leaf] + b" "
    else:
        extra = {"unused": True}
        blocks[cid_for_structured(extra)] = canonical_dag_json_bytes(extra)
    with pytest.raises(p.SnapshotError):
        parse_chunked(root, blocks, chunked) if kind == "chunk" else parse_snapshot(root, blocks, evidence)


def test_blob_chunk_offsets_and_qualified_limits_cannot_be_changed():
    chunked, _ = synthetic(3)
    root, blocks = chunked.manifest_blocks()
    descriptor = json.loads(blocks[root])
    index = json.loads(blocks[descriptor["blob_pages"][0]])
    target = index["records"][0]["manifest_cid"]
    blob = json.loads(blocks[target])
    blob["chunks"][0]["offset"] = 1
    forged_root, forged = rewrite(blocks, root, target, blob)
    with pytest.raises(p.SnapshotError, match="omitted, duplicated or reordered"):
        parse_chunked(forged_root, forged, chunked)
    with pytest.raises(p.SnapshotError, match="qualified admission limits"):
        p.parse_chunked_snapshot_manifest(root, blocks, repository_id=chunked.repository_id,
                                          expected_commit=chunked.git_commit, expected_tree=chunked.git_tree,
                                          expected_population_cid=chunked.population_cid,
                                          limits=c.ChunkedSnapshotLimits(max_entries=2))


def test_real_git_scope_is_admitted_before_content_claims_can_be_used(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                                       stderr=subprocess.DEVNULL).decode().strip()
    git("init", "-b", "main")
    (root / "module.py").write_bytes(b"value = 1\n")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    request = dict(repository_id="fixture:real-paged", expected_commit=git("rev-parse", "HEAD"),
                   expected_tree=git("rev-parse", "HEAD^{tree}"))
    chunked = c.snapshot_chunked_repository(root, **request)
    cid, blocks = chunked.manifest_blocks()
    admitted = p.admit_chunked_snapshot_manifest(root, cid, blocks, **request)
    projection = c.project_chunked_repository(root, admitted)
    evidence = p.page_snapshot_evidence(projection.snapshot, cid)
    assert parse_snapshot(evidence.root_cid, evidence.blocks, evidence)[0].snapshot_cid == projection.snapshot.snapshot_cid
    descriptor = json.loads(blocks[cid])
    index = json.loads(blocks[descriptor["blob_pages"][0]])
    target = index["records"][0]["manifest_cid"]
    claim = json.loads(blocks[target])
    claim["source_cid"] = cid_for_bytes(b"substituted")
    forged_root, forged = rewrite(blocks, cid, target, claim)
    # Metadata admission is explicitly not content verification.
    unverified = p.admit_chunked_snapshot_manifest(root, forged_root, forged, **request)
    with pytest.raises(c.GitSnapshotError, match="verify chunked manifest"):
        c.project_chunked_repository(root, unverified)
    with pytest.raises(p.SnapshotError):
        p.admit_chunked_snapshot_manifest(root, cid, blocks, **{**request, "expected_commit": "0" * 40})


@pytest.mark.parametrize("attack", ["empty", "oversized_reference", "block_count", "frame"])
def test_invalid_mapping_envelope_refuses_before_dag_decoding(attack, monkeypatch):
    chunked, _ = synthetic(1)
    chunked = replace(chunked, limits=c.ChunkedSnapshotLimits(max_entries=1))
    root, blocks = chunked.manifest_blocks()
    leaf = next(cid for cid in blocks if cid != root)
    if attack == "empty":
        blocks[leaf] = b""
    elif attack == "oversized_reference":
        blocks["b" * 1024] = blocks.pop(leaf)
    elif attack == "block_count":
        blocks[cid_for_structured({"unused": True})] = b"1"
    else:
        blocks[leaf] = b"x" * (c.MAX_FRAME_BYTES + 1)
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid envelope reached JSON decoding")
    monkeypatch.setattr(p.json, "loads", forbidden)
    with pytest.raises(p.SnapshotError):
        p.parse_chunked_snapshot_manifest(root, blocks, repository_id=chunked.repository_id,
                                          expected_commit=chunked.git_commit, expected_tree=chunked.git_tree,
                                          expected_population_cid=chunked.population_cid,
                                          limits=chunked.limits)

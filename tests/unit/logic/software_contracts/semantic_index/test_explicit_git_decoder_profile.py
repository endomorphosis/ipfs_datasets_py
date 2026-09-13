"""Real packed content, resource admission and strict profile-bound manifests."""
from dataclasses import asdict
import json
import resource
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_byte_chunks, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index import chunked_snapshot as C
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_snapshot as P
from ipfs_datasets_py.logic.software_contracts.semantic_index import streaming_scanner as S
from ipfs_datasets_py.logic.software_contracts.semantic_index import git_decoder_profile as D


def git(root, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                                   stderr=subprocess.DEVNULL).decode().strip()


def commit(root):
    git(root, "add", "-A")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    return dict(repository_id="fixture:explicit-decoder", expected_commit=git(root, "rev-parse", "HEAD"),
                expected_tree=git(root, "rev-parse", "HEAD^{tree}"))


@pytest.fixture
def source(tmp_path):
    root=tmp_path/"source";root.mkdir();git(root,"init","-b","main")
    (root/"module.py").write_bytes(b"def add(a,b): return a+b\n")
    return root,commit(root)

PROFILE = D.GitBlobDecoderProfile(D.EXPLICIT_DECODER_ADDRESS_BYTES)
BUDGET = D.GitBlobDecoderBudget(D.EXPLICIT_DECODER_ADDRESS_BYTES)


def explicit(root, request, **kwargs):
    return C.snapshot_chunked_repository(root, **request, decoder_profile=PROFILE,
                                        decoder_budget=BUDGET, **kwargs)


def parse(snapshot, *, profile=PROFILE, budget=BUDGET, root_payload=None):
    cid, blocks = snapshot.manifest_blocks()
    if root_payload is not None:
        del blocks[cid]
        cid = cid_for_structured(root_payload)
        blocks[cid] = canonical_dag_json_bytes(root_payload)
    return P.parse_chunked_snapshot_manifest(cid, blocks,
        repository_id=snapshot.repository_id, expected_commit=snapshot.git_commit,
        expected_tree=snapshot.git_tree, expected_population_cid=snapshot.population_cid,
        limits=snapshot.limits, decoder_profile=profile, decoder_budget=budget)


@pytest.mark.parametrize('value', [True, None, '268435456', 0, 1024, 192*1024**2, 512*1024**2])
def test_only_supported_fixed_profiles_and_caller_budgets_are_constructible(value):
    with pytest.raises(C.SnapshotError, match='unsupported'):
        D.GitBlobDecoderProfile(value)
    with pytest.raises(C.SnapshotError, match='unsupported'):
        D.GitBlobDecoderBudget(value)


def test_unbudgeted_or_untyped_explicit_profile_refuses_before_metadata_or_content(source, monkeypatch):
    root, request = source
    monkeypatch.setattr(C, '_observe', lambda *a: pytest.fail('unadmitted Git observation'))
    with pytest.raises(C.SnapshotError, match='resource budget'):
        C.snapshot_chunked_repository(root, **request, decoder_profile=PROFILE)
    with pytest.raises(C.SnapshotError, match='typed'):
        C.snapshot_chunked_repository(root, **request, decoder_profile=PROFILE,
                                      decoder_budget=asdict(BUDGET))


def test_v1_default_and_v2_explicit_are_distinct_closed_profiles(source):
    root, request = source
    legacy = C.snapshot_chunked_repository(root, **request)
    upgraded = explicit(root, request)
    legacy_cid, legacy_blocks = legacy.manifest_blocks()
    upgraded_cid, upgraded_blocks = upgraded.manifest_blocks()
    old = json.loads(legacy_blocks[legacy_cid]); new = json.loads(upgraded_blocks[upgraded_cid])
    assert old['schema'].endswith('@1') and new['schema'].endswith('@2')
    assert 'git_decoder_profile' not in old
    assert old['git_decoder_address_bytes'] == 128*1024**2 == C.MAX_GIT_DECODER_ADDRESS_BYTES
    assert new['git_decoder_address_bytes'] == 256*1024**2
    assert new['git_decoder_profile'] == PROFILE.payload()
    assert legacy.blobs == upgraded.blobs and legacy.entries == upgraded.entries
    assert legacy_cid != upgraded_cid
    assert parse(legacy, profile=D.DEFAULT_DECODER_PROFILE, budget=D.DEFAULT_DECODER_BUDGET) == legacy
    assert parse(upgraded) == upgraded
    with pytest.raises(C.SnapshotError, match='v1 request'):parse(legacy)
    with pytest.raises(C.SnapshotError, match='request'):parse(upgraded, profile=D.DEFAULT_DECODER_PROFILE)
    with pytest.raises(C.SnapshotError, match='resource budget'):parse(upgraded, budget=D.DEFAULT_DECODER_BUDGET)


@pytest.mark.parametrize('fault', ['limit', 'cache', 'timeout', 'launcher', 'source', 'authority_type', 'extra', 'schema'])
def test_manifest_profile_substitution_is_denied_even_with_rehashed_root(source, fault):
    root, request = source; snapshot = explicit(root, request)
    cid, blocks = snapshot.manifest_blocks(); body = json.loads(blocks[cid])
    value = body['git_decoder_profile']
    if fault == 'limit':value['address_space_bytes'] = 512*1024**2
    elif fault == 'cache':value['git_config']['core.packedGitLimit'] = '268435456'
    elif fault == 'timeout':value['command_timeout_seconds'] = '20.0'
    elif fault == 'launcher':value['launcher_sha256'] = '0'*64
    elif fault == 'source':value['source_sha256']['chunked_snapshot.py'] = '0'*64
    elif fault == 'authority_type':value['source_execution'] = 0
    elif fault == 'extra':value['admitted'] = True
    else:body['schema'] = 'ipfs-datasets.git-chunked-snapshot@3'
    with pytest.raises(C.SnapshotError, match='profile|schema'):
        parse(snapshot, root_payload=body)


def test_all_blob_consumers_require_explicit_matching_request_and_budget(source, monkeypatch):
    root, request = source;snapshot = explicit(root, request);blob = snapshot.blobs[0]
    monkeypatch.setattr(C, '_hash_blob', lambda *a, **kw: pytest.fail('unauthorized content read'))
    monkeypatch.setattr(S, '_hash_blob', lambda *a, **kw: pytest.fail('unauthorized content analysis'))
    calls = [lambda **kw:C.read_chunked_blob_frame(root, snapshot, git_object_oid=blob.git_object_oid, chunk_index=0, **kw),
             lambda **kw:C.project_chunked_repository(root, snapshot, **kw),
             lambda **kw:S.scan_chunked_repository_streaming(root, snapshot, **kw)]
    for call in calls:
        with pytest.raises(C.SnapshotError, match='request'):call()
        with pytest.raises(C.SnapshotError, match='resource budget'):call(decoder_profile=PROFILE)


def test_explicit_profile_is_the_real_child_address_space_bound(source, monkeypatch):
    root, request = source
    (root/'module.py').write_bytes(b'x=1\n'*20000);commit(root)
    oid = git(root, 'rev-parse', 'HEAD:module.py')
    original, children = C.subprocess.Popen, []
    def start(*args, **kwargs):
        child = original(*args, **kwargs);children.append(child);return child
    monkeypatch.setattr(C.subprocess, 'Popen', start)
    frames = C._git_blob_frames(root, oid, (root/'module.py').stat().st_size, 1, decoder_profile=PROFILE)
    try:
        assert len(next(frames)) == 1
        assert resource.prlimit(children[0].pid, resource.RLIMIT_AS) == (256*1024**2,)*2
    finally:frames.close()
    assert children[0].returncode is not None


@pytest.fixture(scope='module')
def packed_oversized(tmp_path_factory):
    root = tmp_path_factory.mktemp('explicit-profile-packed')
    git(root, 'init', '-b', 'main')
    size = 82*1024**2
    for index in range(2):
        # Sparse inputs and compressed delta storage keep physical disk small.
        # Both complete Git blob streams still contain all 82 MiB of bytes.
        with (root/f'packed-{index}.bin').open('wb') as stream:
            stream.seek(size-1);stream.write(b'\0')
            stream.seek(size//2);stream.write(bytes([index+1]))
    request = commit(root)
    git(root, 'repack', '-adf', '--window=10', '--depth=10', '--window-memory=256m')
    indexes = list((root/'.git/objects/pack').glob('*.idx'))
    assert len(indexes) == 1
    details = git(root, 'verify-pack', '-v', str(indexes[0]))
    assert any(len(row.split()) == 7 and row.split()[1] == 'blob' for row in details.splitlines())
    return root, request, size


def test_real_large_packed_delta_refuses_128_and_verifies_all_bytes_under_admitted_256(packed_oversized):
    root, request, size = packed_oversized
    limits = C.ChunkedSnapshotLimits(max_stream_bytes=2*size)
    with pytest.raises(C.GitBlobDecoderError) as refused:
        C.snapshot_chunked_repository(root, **request, limits=limits)
    assert refused.value.decoder_address_limit_bytes == 128*1024**2
    snapshot = explicit(root, request, limits=limits)
    assert len(snapshot.blobs) == len(snapshot.entries) == 2
    assert sum(blob.size_bytes for blob in snapshot.blobs) == 2*size
    by_oid = {blob.git_object_oid:blob for blob in snapshot.blobs}
    for entry in snapshot.entries:
        with (root/entry.path).open('rb') as stream:
            expected = cid_for_byte_chunks(iter(lambda:stream.read(C.MAX_FRAME_BYTES), b''),
                                           max_chunk_bytes=C.MAX_FRAME_BYTES)
        blob = by_oid[entry.git_object_oid]
        assert blob.source_cid == expected
        assert sum(frame.size_bytes for frame in blob.chunks) == size
        assert max(frame.size_bytes for frame in blob.chunks) <= C.MAX_FRAME_BYTES
    projection = C.project_chunked_repository(root, snapshot, decoder_profile=PROFILE, decoder_budget=BUDGET)
    assert projection.unique_blob_bytes_verified == 2*size and projection.retained_source_bytes == 0
    assert all(entry.opaque_reason == 'analysis_budget_exceeded' for entry in projection.snapshot.entries)
    assert C.MAX_MATERIALIZED_FILE_BYTES == 4*1024**2 and C.MAX_RETAINED_SOURCE_BYTES == 128*1024**2
    assert all(len(raw) <= C.MAX_FRAME_BYTES for raw in snapshot.manifest_blocks()[1].values())
    assert parse(snapshot) == snapshot

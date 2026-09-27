"""Streaming source populations retain identities, not an aggregate byte cache."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index import chunked_snapshot as c
from ipfs_datasets_py.logic.software_contracts.semantic_index import streaming_scanner as s
from ipfs_datasets_py.logic.software_contracts.semantic_index.paged_snapshot import page_snapshot_evidence
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import SnapshotError


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0', '-C', str(root), *args],
                                   stderr=subprocess.DEVNULL).decode().strip()


def test_malformed_response_after_child_exit_does_not_signal_reaped_group(monkeypatch):
    monkeypatch.setattr(s, '_worker_command', lambda: [sys.executable, '-I', '-c',
        'import sys; sys.stdin.buffer.read(); sys.stdout.write("malformed")'])
    signals = []
    monkeypatch.setattr(s.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(s.StreamingAnalysisError, match='invalid_worker_response'):
        s._run_worker({'operation': 'assemble'}, b'{}', s.StreamingScanLimits(), output_limit=4096)
    assert signals == []


def commit(root):
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    return dict(repository_id='fixture:streaming', expected_commit=git(root, 'rev-parse', 'HEAD'),
                expected_tree=git(root, 'rev-parse', 'HEAD^{tree}'))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    (root / 'module.py').write_bytes(b'def add(a, b):\n    return a+b\n')
    return root


def capture(root, limits=c.ChunkedSnapshotLimits()):
    return c.snapshot_chunked_repository(root, **commit(root), limits=limits)


def paged_legacy(root, chunked, max_file_bytes=c.MAX_MATERIALIZED_FILE_BYTES):
    projection = c.project_chunked_repository(root, chunked, max_file_bytes=max_file_bytes)
    snapshot = projection.snapshot
    state = RepositoryScanner(repository_id=chunked.repository_id).scan_snapshot(snapshot,
                  {entry.source_key:entry.captured_bytes for entry in snapshot.entries if entry.captured_bytes is not None})
    evidence = page_snapshot_evidence(snapshot, chunked.snapshot_cid)
    return snapshot, replace(state, artifacts=tuple(item for item in state.artifacts
                                 if item.artifact_id != 'artifact:snapshot-evidence') + (evidence.artifact(),))


def test_streamed_python_pytest_and_opaque_population_matches_paged_legacy(source):
    (source/'tests').mkdir()
    (source/'conftest.py').write_text('import pytest\n@pytest.fixture(autouse=True)\ndef base(): return 1\n')
    (source/'tests/conftest.py').write_text('import pytest\n@pytest.fixture\ndef local(base): return base\n')
    (source/'tests/test_module.py').write_text('import pytest\nfrom module import add\n@pytest.mark.parametrize("x", [1,2])\ndef test_add(local,x): assert add(local,x)\n')
    (source/'pytest.ini').write_text('[pytest]\naddopts=-q\n')
    (source/'requirements.txt').write_text('pytest\n')
    (source/'opaque.bin').write_bytes(b'\xff\x00')
    (source/'bad.py').write_text('def broken(\n')
    os.symlink('module.py', source/'link.py')
    chunked = capture(source)
    snapshot, legacy = paged_legacy(source, chunked)
    streamed = s.scan_chunked_repository_streaming(source, chunked)
    assert streamed.projection.snapshot.to_dict() == snapshot.to_dict()
    assert all(entry.captured_bytes is None for entry in streamed.projection.snapshot.entries)
    assert streamed.state.to_dict() == legacy.to_dict()
    assert streamed.state.state_cid == legacy.state_cid
    observed = streamed.observation
    assert observed['retained_snapshot_source_bytes'] == 0
    assert observed['peak_captured_blob_bytes'] <= c.MAX_MATERIALIZED_FILE_BYTES
    assert observed['peak_worker_rss_bytes'] < s.WORKER_ADDRESS_BYTES
    assert observed['analysis_process_profile']['address_space_limit_bytes'] == s.WORKER_ADDRESS_BYTES


def test_individual_ast_and_semantic_record_refusals_are_structured(source):
    (source/'module.py').write_text('values = [' + ','.join(str(i) for i in range(200)) + ']\n')
    chunked = capture(source)
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s.scan_chunked_repository_streaming(source, chunked, limits=s.StreamingScanLimits(max_ast_nodes=50))
    assert failure.value.code == 'ast_node_budget'
    assert failure.value.observation()['complete_analysis_authority'] is False
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s.scan_chunked_repository_streaming(source, chunked, limits=s.StreamingScanLimits(max_record_bytes=512))
    assert failure.value.code == 'semantic_record_frame'


def test_aggregate_fact_refusal_does_not_drop_inputs(source):
    for i in range(12):
        (source/f'file_{i}.py').write_text(f'def function_{i}(x): return x+1\n')
    chunked = capture(source)
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s.scan_chunked_repository_streaming(source, chunked,
              limits=s.StreamingScanLimits(max_fact_bytes=16000, max_file_fact_bytes=12000))
    assert failure.value.code == 'aggregate_fact_budget'


@pytest.mark.parametrize('attack', ['timeout', 'output'])
def test_owned_worker_is_killed_and_reaped_on_refusal(monkeypatch, attack):
    original = s.subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(s.subprocess, 'Popen', spawn)
    command = 'import time; time.sleep(60)' if attack == 'timeout' else 'import os,time; os.write(1,b"x"*16384); time.sleep(60)'
    monkeypatch.setattr(s, '_worker_command', lambda: [sys.executable, '-I', '-c', command])
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s._run_worker({'operation':'analysis'}, b'', s.StreamingScanLimits(worker_timeout_seconds=1), output_limit=1024)
    assert failure.value.code == ('worker_timeout' if attack == 'timeout' else 'worker_output_limit')
    assert len(children) == 1 and children[0].returncode is not None
    assert not Path(f'/proc/{children[0].pid}').exists()


def test_worker_kernel_profile_is_observed_and_target_code_is_not_executed(source):
    marker = source/'should-not-exist'
    raw = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("executed")\n').encode()
    facts, measured = s._run_worker({'operation':'analysis', 'repository_id':'fixture:no-execution',
          'path':'module.py', 'kind':'python', 'source_cid':cid_for_bytes(raw)}, raw, s.StreamingScanLimits(),
          output_limit=s.MAX_FILE_FACT_BYTES + 4096)
    assert facts['source_cid'] == cid_for_bytes(raw)
    assert measured['address_space_limit_bytes'] == s.WORKER_ADDRESS_BYTES
    assert measured['cpu_limit_seconds'] == s.WORKER_CPU_SECONDS
    assert not marker.exists()


def test_content_substitution_and_source_drift_refuse_complete_state(source, monkeypatch):
    chunked = capture(source)
    forged = replace(chunked, blobs=(replace(chunked.blobs[0],source_cid=cid_for_bytes(b'false')),))
    with pytest.raises(s.StreamingAnalysisError, match='committed_content_mismatch'):
        s.scan_chunked_repository_streaming(source, forged)
    original = s._run_worker
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        (source/'module.py').write_text('changed = True\n')
        git(source, 'add', 'module.py')
        return result
    monkeypatch.setattr(s, '_run_worker', drift)
    with pytest.raises(SnapshotError):
        s.scan_chunked_repository_streaming(source, chunked)


def test_more_than_128_mib_of_real_committed_ordinary_sources_is_fully_consumed(source, tmp_path):
    # Unique modest Python blobs: a real 130 MiB population, with small ASTs.
    (source/'module.py').unlink()
    expected = {}
    padding = b'#' + b'x' * (2 * 1024 * 1024 - 32) + b'\n'
    for i in range(66):
        raw = (f'# file {i:05}\n').encode() + padding
        name = f'file_{i:03}.py'
        (source/name).write_bytes(raw)
        expected[name] = (len(raw), cid_for_bytes(raw))
    del raw, padding
    total = sum(size for size, _ in expected.values())
    assert total > c.MAX_RETAINED_SOURCE_BYTES
    chunked = capture(source, c.ChunkedSnapshotLimits(max_stream_bytes=160 * 1024 * 1024))
    with pytest.raises(SnapshotError, match='retained source byte budget'):
        c.project_chunked_repository(source, chunked)
    tracemalloc.start()
    tracemalloc.reset_peak()
    result = s.scan_chunked_repository_streaming(source, chunked)
    _, parent_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(result.projection.snapshot.entries) == len(expected)
    assert all(not entry.is_opaque and entry.captured_bytes is None and
               (entry.size_bytes, entry.source_cid) == expected[entry.path]
               for entry in result.projection.snapshot.entries)
    assert result.projection.unique_blob_bytes_verified == total
    assert result.observation['ordinary_source_bytes_submitted'] == total
    assert len(result.state.symbols) == len(expected)
    assert not any(item.confidence == 'opaque' for item in result.state.artifacts)
    assert parent_peak < 64 * 1024 * 1024
    assert result.observation['peak_worker_rss_bytes'] < s.WORKER_ADDRESS_BYTES
    receipt = {**result.observation, 'parent_python_tracemalloc_peak_bytes':parent_peak,
               'parent_measurement_scope':'Python allocations during streaming scan; excludes children and native allocator RSS',
               'source_bytes':total, 'all_population_entries_verified':True, 'all_sources_ordinary':True}
    (tmp_path/'streaming-memory-receipt.json').write_text(json.dumps(receipt,indent=2))
    print('STREAMING_MEMORY_RECEIPT=' + json.dumps({'path':str(tmp_path/'streaming-memory-receipt.json'), **receipt},sort_keys=True))


def test_real_individual_semantic_artifact_over_one_mib_is_refused(source):
    (source/'module.py').write_bytes(b'value = "' + b'x' * (600 * 1024) + b'"\n')
    chunked = capture(source)
    assert chunked.blobs[0].size_bytes < c.MAX_MATERIALIZED_FILE_BYTES
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s.scan_chunked_repository_streaming(source, chunked)
    assert failure.value.code == 'semantic_record_frame'
    assert failure.value.limit == c.MAX_FRAME_BYTES
    assert failure.value.observed > c.MAX_FRAME_BYTES


def test_worker_refuses_an_unqualified_source_profile():
    raw=b'x = 1\n'
    with pytest.raises(s.StreamingAnalysisError) as failure:
        s._run_worker({'operation':'analysis', 'path':'module.py', 'repository_id':'fixture:profile',
               'kind':'python', 'source_cid':cid_for_bytes(raw), 'expected_worker_source_sha256':'0'*64},
               raw,s.StreamingScanLimits(),output_limit=s.MAX_FILE_FACT_BYTES+4096)
    assert failure.value.code == 'worker_source_profile_changed'

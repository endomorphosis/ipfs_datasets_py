"""Real small committed inputs: raw fact coverage is not semantic assembly."""
from dataclasses import asdict, replace
import errno
import json
import os
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured, cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index import chunked_snapshot as chunks
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_scan as scan
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_store as pages
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_worker as worker
from ipfs_datasets_py.logic.software_contracts.semantic_index import streaming_scanner as old


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0',
        '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    (root/'module.py').write_text('def add(a, b): return a+b\n')
    return root, tmp_path


def capture(root):
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    request = dict(expected_commit=git(root, 'rev-parse', 'HEAD'), expected_tree=git(root, 'rev-parse', 'HEAD^{tree}'),
                   repository_id='fixture:paged-raw')
    return chunks.snapshot_chunked_repository(root, **request), request


def store_at(path, **changes):
    profile = pages.PagedFactProfile()
    budget = pages.FactSpoolBudget(**(dict(max_stored_bytes=8*1024**2, max_blocks=10000,
        max_records=10000, max_io_bytes=128*1024**2, max_work_items=200000) | changes))
    return pages.OwnedFactStore(path, profile=profile, budget=budget)


def run(root, chunked, request, store, **kwargs):
    return scan.scan_chunked_repository_paged_facts(root, chunked, **request,
        expected_chunked_snapshot_cid=chunked.snapshot_cid, store=store, profile=store.profile, budget=store.budget, **kwargs)


def file_records(store, root_cid):
    root = store.get(root_cid)
    for raw, cid in pages.iter_fact_index(store, root['coverage_index']):
        coverage = store.get(cid)
        file = store.get(coverage['file_root_cid'])
        yield coverage, file, {group: [store.get(value) for _, value in pages.iter_fact_index(store, file['indexes'][group])]
                               for group in scan.GROUPS}


def test_real_complete_raw_coverage_preserves_all_files_and_no_global_semantics(fixture, monkeypatch):
    root, tmp = fixture
    (root/'empty.py').write_text('')
    (root/'conftest.py').write_text('import pytest\n@pytest.fixture(autouse=True)\ndef fixture_value(): return 1\n')
    (root/'test_module.py').write_text('from module import add\ndef test_add(fixture_value): assert add(fixture_value, 1)\n')
    (root/'pytest.ini').write_text('[pytest]\naddopts=-q\n')
    (root/'bad.py').write_text('def broken(\n')
    (root/'opaque.bin').write_bytes(b'\xff\x00')
    (root/'copy.py').write_bytes((root/'module.py').read_bytes())
    os.symlink('module.py', root/'link.py')
    chunked, request = capture(root)
    # There is no fallback to global assembly or bundle compilation.
    monkeypatch.setattr(old, '_assemble', lambda *a, **k: pytest.fail('global assembly invoked'))
    with store_at(tmp/'facts') as store:
        result = run(root, chunked, request, store)
        payload = store.get(result.root_cid)
        assert payload['entry_count'] == len(chunked.entries) == 9
        assert payload['unique_blob_count'] == len(chunked.blobs) == 8
        assert payload['unique_blob_bytes_verified'] == sum(blob.size_bytes for blob in chunked.blobs)
        assert payload['request']['implementation'] == worker.implementation_profile()
        assert all(payload[name] is False for name in scan.DENIALS)
        actual = list(file_records(store, result.root_cid))
        assert {c['member']['raw_path_hex'] for c, _, _ in actual} == {e.raw_path_hex for e in chunked.entries}
        assert sorted(c['extraction_ordinal'] for c, _, _ in actual) == list(range(len(chunked.entries)))
        for coverage, file, facts in actual:
            entry = scan.SnapshotEntry.from_dict(coverage['snapshot_entry'])
            assert file['source_cid'] == entry.source_cid
            assert all(file[name] is False for name in scan.DENIALS)
            if file['disposition'] == 'raw-analyzed':
                raw = (root/entry.path).read_bytes()
                expected = old._analyze_one(raw, {'path': entry.path, 'source_cid': entry.source_cid,
                    'kind': entry.kind, 'repository_id': chunked.repository_id}, old.StreamingScanLimits())
                assert facts == {group: expected[group] for group in scan.GROUPS}
            if entry.path in {'link.py', 'opaque.bin'}:
                assert file['disposition'] == 'opaque'
                assert facts['artifacts'][0]['confidence'] == 'opaque'
            if entry.path == 'bad.py':
                assert facts['artifacts'][0]['confidence'] == 'opaque'
        # A test's unresolved fixture input is retained; no cross-file edge is invented here.
        tests = next(f for c, _, f in actual if c['snapshot_entry']['path'] == 'test_module.py')
        assert tests['tests'][0]['fixture_parameters'] == ['fixture_value']
        assert not any(e['relation'] == 'uses_fixture' for e in tests['edges'])
        assert result.observation['retained_snapshot_source_bytes'] == 0
        assert result.observation['peak_worker_rss_bytes'] < old.WORKER_ADDRESS_BYTES
        marker = json.loads((store.path/'raw-coverage.json').read_bytes())
        assert marker['root_cid'] == result.root_cid and marker['completion_authority'] is False


def test_opaque_gitlink_has_no_local_import_or_followed_forest(fixture):
    root, tmp = fixture
    _, first = capture(root)
    git(root, 'update-index', '--add', '--cacheinfo', '160000,'+first['expected_commit']+',vendor')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'gitlink')
    (root/'vendor').mkdir()  # an empty, uninitialized gitlink is clean
    request = first | {'expected_commit':git(root,'rev-parse','HEAD'),'expected_tree':git(root,'rev-parse','HEAD^{tree}')}
    chunked = chunks.snapshot_chunked_repository(root, **request)
    with store_at(tmp/'facts') as store:
        result = run(root, chunked, request, store)
        coverage, file, facts = next(row for row in file_records(store,result.root_cid) if row[0]['snapshot_entry']['path']=='vendor')
        assert coverage['member']['object_type'] == 'commit'
        assert file['disposition'] == 'opaque' and file['source_cid'] is None
        assert facts['artifacts'][0]['metadata']['opaque_reason'] == 'symlink_or_nonregular'
        assert list((root/'vendor').iterdir()) == []


def test_target_code_is_never_executed(fixture):
    root, tmp = fixture
    marker = tmp/'executed'
    (root/'module.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("bad")\n')
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        run(root, chunked, request, store)
    assert not marker.exists()


def test_per_file_bound_preserved_while_explicit_spool_removes_small_aggregate_only(fixture):
    root, tmp = fixture
    for i in range(9):
        (root/f'module_{i}.py').write_text(f'def function_{i}(x): return x+1\n')
    chunked, request = capture(root)
    limits = old.StreamingScanLimits(max_fact_bytes=12000, max_file_fact_bytes=8000)
    with pytest.raises(old.StreamingAnalysisError, match='aggregate_fact_budget'):
        old.scan_chunked_repository_streaming(root, chunked, limits=limits)
    with store_at(tmp/'facts') as store:
        result = run(root, chunked, request, store, analysis_limits=limits)
        assert result.observation['raw_fact_bytes'] > limits.max_fact_bytes
        assert result.observation['entries_completed'] == 10
    with store_at(tmp/'small-file-facts') as store:
        with pytest.raises(pages.PagedFactError, match='file_fact_budget|semantic_record_frame|worker_output_limit'):
            run(root, chunked, request, store, analysis_limits=old.StreamingScanLimits(max_file_fact_bytes=256))
        assert not (store.path/'raw-coverage.json').exists()


@pytest.mark.parametrize('attack', ['manifest', 'commit', 'budget', 'source-content', 'worker-profile'])
def test_immutable_request_and_worker_profile_denials(fixture, monkeypatch, attack):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        if attack == 'manifest':
            chunked = replace(chunked, blobs=(replace(chunked.blobs[0], source_cid=cid_for_bytes(b'other')),))
        elif attack == 'commit':
            request = request | {'expected_commit':'1'*40}
        elif attack == 'budget':
            object.__setattr__(store.budget, 'max_records', 10001)
        elif attack == 'source-content':
            original = scan._hash_blob
            def wrong(*args, **kwargs):
                blob, raw = original(*args, **kwargs)
                return replace(blob, source_cid=cid_for_bytes(b'other')), raw
            monkeypatch.setattr(scan, '_hash_blob', wrong)
        else:
            original = scan.implementation_profile
            def wrong():
                result = original()
                result['source_file_count'] += 1
                return result
            monkeypatch.setattr(scan, 'implementation_profile', wrong)
        with pytest.raises(pages.PagedFactError) as failure:
            run(root, chunked, request, store)
        report = failure.value.observation()
        assert report['complete_raw_coverage'] is False and report['completion_authority'] is False
        assert 'usage' in report['progress']
        assert not (store.path/'raw-coverage.json').exists()


@pytest.mark.parametrize('attack', ['source', 'implementation'])
def test_final_fence_refuses_publication_after_valid_facts(fixture, monkeypatch, attack):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        original = scan.verify_raw_fact_coverage
        def drift(*args, **kwargs):
            result = original(*args, **kwargs)
            if attack == 'source':
                (root/'module.py').write_text('changed=True\n')
            else:
                original_profile = scan.implementation_profile
                monkeypatch.setattr(scan, 'implementation_profile', lambda: original_profile() | {'source_file_count': 1})
            return result
        monkeypatch.setattr(scan, 'verify_raw_fact_coverage', drift)
        with pytest.raises(pages.PagedFactError) as failure:
            run(root, chunked, request, store)
        assert failure.value.progress['entries_completed'] == 1
        assert failure.value.progress['stage'] == 'final-fence'
        assert not (store.path/'raw-coverage.json').exists()


def test_spool_refusal_has_bounded_path_counts_stage_and_work(fixture):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts', max_records=1) as store:
        with pytest.raises(pages.PagedFactError, match='spool_records') as failure:
            run(root, chunked, request, store)
        report = failure.value.observation()
        assert report['raw_path_hex'] == 'module.py'.encode().hex()
        assert report['progress']['blobs_verified'] == 1
        assert report['progress']['entries_completed'] == 0
        assert report['progress']['stage'] == 'spooling'
        assert report['progress']['usage']['records'] == 1
        assert len(canonical_dag_json_bytes(report)) < 2048
        assert not (store.path/'raw-coverage.json').exists()


@pytest.mark.parametrize('attack', ['entry-count', 'missing-entry', 'opaque-artifact', 'record-source', 'extraction-order'])
def test_rehashed_complete_root_cannot_omit_or_rebind_coverage(fixture, monkeypatch, attack):
    root, tmp = fixture
    (root/'opaque.bin').write_bytes(b'\xff')
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        original = scan.verify_raw_fact_coverage
        def forged(s, root_cid, **kwargs):
            payload = s.get(root_cid)
            pairs = list(pages.iter_fact_index(s, payload['coverage_index']))
            if attack == 'entry-count':
                payload['entry_count'] = True
            elif attack == 'missing-entry':
                payload['coverage_index'] = pages.build_fact_index(s, pairs[:-1])
            else:
                target = next(i for i, pair in enumerate(pairs) if bytes.fromhex(pair[0]).decode() ==
                              ('opaque.bin' if attack == 'opaque-artifact' else 'module.py'))
                coverage = s.get(pairs[target][1])
                file = s.get(coverage['file_root_cid'])
                if attack == 'extraction-order':
                    coverage['extraction_ordinal'] = True
                elif attack == 'opaque-artifact':
                    file['indexes']['artifacts'] = pages.build_fact_index(s, ())
                else:
                    records = list(pages.iter_fact_index(s, file['indexes']['symbols']))
                    record = scan.SymbolRecord.from_dict(s.get(records[0][1]))
                    bad = replace(record, source_cid=cid_for_bytes(b'other')).to_dict()
                    records[0] = (records[0][0], s.put(bad))
                    file['indexes']['symbols'] = pages.build_fact_index(s, records)
                coverage['file_root_cid'] = s.put(file)
                pairs[target] = (pairs[target][0], s.put(coverage))
                payload['coverage_index'] = pages.build_fact_index(s, pairs)
            return original(s, s.put(payload), **kwargs)
        monkeypatch.setattr(scan, 'verify_raw_fact_coverage', forged)
        with pytest.raises(pages.PagedFactError):
            run(root, chunked, request, store)
        assert not (store.path/'raw-coverage.json').exists()


def test_disk_full_during_scan_never_publishes(fixture, monkeypatch):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        original = store.put
        def failed(value):
            if isinstance(value, dict) and value.get('schema') == scan.COVERAGE_SCHEMA:
                raise OSError(errno.ENOSPC, 'fixture disk full')
            return original(value)
        monkeypatch.setattr(store, 'put', failed)
        with pytest.raises(pages.PagedFactError) as failure:
            run(root, chunked, request, store)
        assert failure.value.progress['workers_completed'] == 1
        assert not (store.path/'raw-coverage.json').exists()


def test_published_raw_pages_reopen_readonly_with_exact_request_and_reverify(fixture):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts') as store:
        result = run(root, chunked, request, store)
        expected_request = store.get(result.root_cid)['request']
        profile, budget = store.profile, store.budget
        with pytest.raises(BlockingIOError):
            pages.OwnedFactStore.open_published(store.path, expected_request_cid=result.request_cid,
                expected_root_cid=result.root_cid, profile=profile, budget=budget)
    original_bytes = {p.name:p.read_bytes() for p in (tmp/'facts').iterdir()}
    with pages.OwnedFactStore.open_published(tmp/'facts', expected_request_cid=result.request_cid,
            expected_root_cid=result.root_cid, profile=profile, budget=budget) as reader:
        scan.verify_raw_fact_coverage(reader, result.root_cid, expected_request=expected_request, chunked=chunked)
        with pytest.raises(pages.PagedFactError):
            reader.put({'attempted':'mutation'})
        with pytest.raises(pages.PagedFactError):
            reader.bind_request({'attempted':'reuse'})
    assert {p.name:p.read_bytes() for p in (tmp/'facts').iterdir()} == original_bytes
    with pytest.raises(pages.PagedFactError):
        pages.OwnedFactStore.open_published(tmp/'facts', expected_request_cid=cid_for_structured({'wrong':True}),
            expected_root_cid=result.root_cid, profile=profile, budget=budget)


def test_unpublished_cas_cannot_be_reopened_as_a_complete_result(fixture):
    root, tmp = fixture
    chunked, request = capture(root)
    with store_at(tmp/'facts', max_records=1) as store:
        with pytest.raises(pages.PagedFactError):
            run(root, chunked, request, store)
        request_cid, profile, budget = store._request, store.profile, store.budget
    with pytest.raises((pages.PagedFactError, FileNotFoundError)):
        pages.OwnedFactStore.open_published(tmp/'facts', expected_request_cid=request_cid,
            expected_root_cid=cid_for_structured({'invented':'root'}), profile=profile, budget=budget)

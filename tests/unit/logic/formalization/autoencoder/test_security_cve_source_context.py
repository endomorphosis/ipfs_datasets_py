"""Complete-file context from authored exact Git objects and native corpus rows."""
import base64
from dataclasses import asdict
import hashlib
import io
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_cve_source_context as context
from .test_security_cve_corpus import scenario  # noqa: F401


def _git(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _tree(entries):
    entries.sort(key=lambda x: (x['path'] + ('/' if x['type'] == 'tree' else '')).encode())
    raw = b''.join(x['mode'].lstrip('0').encode() + b' ' + x['path'].encode() + b'\0' + bytes.fromhex(x['sha']) for x in entries)
    sha = _git('tree', raw)
    return sha, {'sha': sha, 'tree': entries, 'truncated': False}


@pytest.fixture
def source_case(scenario, tmp_path):
    args, _, _, _ = scenario
    receipt = context.corpus_api.ingest_security_corpus(**args)
    objects, calls, bodies = {}, [], {}
    for split in context.corpus_api.SPLITS:
        url = 'https://github.com/authored-fixture/' + split
        for fixed in [False, True]:
            revision = ('1' if fixed else '2') * 40
            body = f'# Complete {split} module, not a reconstructed diff\nCONSTANT = {2 if fixed else 1}\n\ndef complete_{split}(value):\n    return value + CONSTANT\n'.encode()
            sha = _git('blob', body); bodies[(split, fixed)] = body
            request = context.GitSourceRequest(url, 'blobs', sha)
            objects[request.key] = {'sha': sha, 'encoding': 'base64', 'content': base64.b64encode(body).decode(), 'size': len(body)}
            subtree, sub = _tree([{'path': 'check.py', 'mode': '100644', 'type': 'blob', 'sha': sha}])
            objects[context.GitSourceRequest(url, 'trees', subtree).key] = sub
            tree, root = _tree([{'path': 'src', 'mode': '040000', 'type': 'tree', 'sha': subtree}])
            objects[context.GitSourceRequest(url, 'trees', tree).key] = root
            objects[context.GitSourceRequest(url, 'commits', revision).key] = {'sha': revision, 'tree': {'sha': tree}, 'parents': [{'sha': '2' * 40}] if fixed else []}
    def fetch(request, maximum):
        calls.append((request, maximum))
        return context._json(objects[request.key])
    return {'corpus': args['output'], 'expected_manifest_sha256': receipt['manifest_sha256'], 'output': tmp_path / 'complete-source', 'fetcher': fetch}, objects, calls, bodies


def test_complete_native_source_and_code_units_replay_without_network(source_case):
    args, _, calls, bodies = source_case
    receipt = context.recover_security_source_context(**args)
    loaded = context.load_security_source_context(args['output'], expected_manifest_sha256=receipt['manifest_sha256'])
    assert receipt['complete_file_count'] == 6 and receipt['valid_ast_file_count'] == 6
    assert receipt['function_count'] == 6 and receipt['frontier_count'] == 0
    assert receipt['request_count'] == len(calls) == 24
    assert loaded['manifest']['fragment_reconstruction_used'] is False
    assert loaded['proof_authority'] is False and loaded['source_semantics_verified'] is False
    assert len(loaded['records']) == 15  # Three exact origin records plus twelve new records.
    for entry in loaded['entries']:
        fixed = entry['polarity'] == 'fixed'
        assert entry['revision'] == ('1' if fixed else '2') * 40
        assert (args['output'] / entry['body_path']).read_bytes() == bodies[entry['split'], fixed]
        assert entry['body_sha256'] != hashlib.sha256(b'def check(value):\n    return value\n').hexdigest()
    # No canonical classification target is mixed into the complete file input.
    assert all('cwe_id' not in record.payload for record in loaded['records'] if 'source_provenance' not in record.payload)


@pytest.mark.parametrize('parents', [[], [{'sha': '2' * 40}, {'sha': '3' * 40}]])
def test_missing_or_merge_parent_is_explicit_frontier_never_first_parent_guess(source_case, parents):
    args, objects, calls, _ = source_case
    for key, value in objects.items():
        if '/commits/' in key and value['sha'] == '1' * 40: value['parents'] = parents
    receipt = context.recover_security_source_context(**args)
    loaded = context.load_security_source_context(args['output'], expected_manifest_sha256=receipt['manifest_sha256'])
    assert receipt['complete_file_count'] == 0 and receipt['frontier_count'] == 6
    assert len(calls) == 3 and {row['reason'] for row in loaded['frontiers']} == {'unique_parent_unavailable'}


def test_missing_path_is_not_reconstructed_or_remapped(source_case):
    args, objects, _, _ = source_case
    key = next(key for key in objects if '/commits/' in key)
    empty_sha, empty = _tree([])
    request = context.GitSourceRequest('https://github.com/authored-fixture/train', 'trees', empty_sha)
    objects[key]['tree']['sha'] = empty_sha; objects[request.key] = empty
    receipt = context.recover_security_source_context(**args)
    loaded = context.load_security_source_context(args['output'], expected_manifest_sha256=receipt['manifest_sha256'])
    assert any('path_absent_at_exact_revision' in item['reason'] for item in loaded['frontiers'])


@pytest.mark.parametrize('kind', ['commit_revision', 'tree_preimage', 'blob_preimage', 'blob_size', 'tree_truncated'])
def test_wrong_source_objects_cannot_publish_context(source_case, kind):
    args, objects, _, _ = source_case
    wanted = 'commits' if kind == 'commit_revision' else ('trees' if kind.startswith('tree') else 'blobs')
    key = next(k for k in objects if '/' + wanted + '/' in k)
    if kind == 'commit_revision': objects[key]['sha'] = 'f' * 40
    elif kind == 'tree_preimage': objects[key]['tree'][0]['path'] = 'other.py'
    elif kind == 'blob_preimage': objects[key]['content'] = base64.b64encode(b'x' * objects[key]['size']).decode()
    elif kind == 'blob_size': objects[key]['size'] += 1
    else: objects[key]['truncated'] = True
    with pytest.raises(ValueError): context.recover_security_source_context(**args)
    assert not args['output'].exists()


def test_transport_failure_accounted_and_budget_stops_further_requests(source_case):
    args, _, calls, _ = source_case
    def fetch(request, maximum):
        calls.append((request, maximum))
        raise context.FetchUnavailable('http_error', response_bytes=5)
    args['fetcher'] = fetch
    args['budget'] = {**context._budget(None), 'max_requests': 1}
    receipt = context.recover_security_source_context(**args)
    loaded = context.load_security_source_context(args['output'], expected_manifest_sha256=receipt['manifest_sha256'])
    assert len(calls) == 1 and receipt['response_body_bytes'] == 5
    assert receipt['complete_file_count'] == 0 and receipt['frontier_count'] == 6
    assert {x['reason'] for x in loaded['frontiers']} == {'http_error', 'transport_budget_exhausted'}


def test_oversized_injected_fetcher_rejected(source_case):
    args, _, _, _ = source_case
    args['fetcher'] = lambda request, maximum: b'x' * (maximum + 1)
    with pytest.raises(ValueError, match='bounded byte response'): context.recover_security_source_context(**args)
    assert not args['output'].exists()


def test_public_fetch_is_anonymous_exact_object_and_accounts_oversize(monkeypatch):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return io.BytesIO(b'x' * 40)
    monkeypatch.setattr(context, 'build_opener', lambda *_: Opener())
    request = context.GitSourceRequest('https://github.com/authored-fixture/train', 'commits', '1' * 40)
    with pytest.raises(context.FetchUnavailable) as failure:
        context.fetch_public_git_object(request, 20)
    assert failure.value.reason == 'response_too_large' and failure.value.response_bytes == 21
    assert calls[0][0].full_url == request.url and calls[0][1] == 30
    assert not any(key.lower() == 'authorization' for key in calls[0][0].headers)


def test_partial_timeout_keeps_received_byte_accounting():
    class Partial:
        def __init__(self): self.calls = 0
        def read(self, maximum): return self.read1(maximum)
        def read1(self, maximum):
            self.calls += 1
            if self.calls == 1: return b'partial'
            raise TimeoutError()
    with pytest.raises(context.FetchUnavailable) as failure:
        context._response_bytes(Partial(), 100)
    assert failure.value.reason == 'network_error' and failure.value.response_bytes == 7


@pytest.mark.parametrize('value', ['../secret.py', '/root/private.py', 'src//file.py', 'src/./file.py', 'src/../file.py', 'src/%2e.py', 'src\\file.py'])
def test_noncanonical_paths_reject_without_io(value):
    with pytest.raises(ValueError): context._path(value)


def test_pinned_corpus_hash_drift_refuses_before_any_network(source_case):
    args, _, calls, _ = source_case
    args['expected_manifest_sha256'] = '0' * 64
    with pytest.raises(ValueError): context.recover_security_source_context(**args)
    assert calls == []


def test_benchmark_family_rejected_before_network(source_case, monkeypatch):
    args, _, calls, _ = source_case
    original = context.BenchmarkExclusions.excludes_family
    monkeypatch.setattr(context.BenchmarkExclusions, 'excludes_family', lambda self, value: 'authored-fixture/train' in value or original(self, value))
    with pytest.raises(ValueError, match='benchmark'): context.recover_security_source_context(**args)
    assert calls == []


@pytest.mark.parametrize('change', ['body', 'proof', 'entry_revision', 'omit_entry', 'extra_metadata', 'commit_authority', 'total_bytes', 'file_budget', 'response_limit', 'failure_status'])
def test_recovery_loader_rejects_drift_even_with_repinned_outer_manifest(source_case, change):
    args, _, _, _ = source_case
    receipt = context.recover_security_source_context(**args)
    path = args['output'] / 'manifest.json'; manifest = json.loads(path.read_bytes())
    if change == 'body': (args['output'] / manifest['entries'][0]['body_path']).write_bytes(b'changed')
    elif change == 'proof': manifest['proof_authority'] = True
    elif change == 'entry_revision': manifest['entries'][0]['revision'] = 'f' * 40
    elif change == 'omit_entry': manifest['entries'].pop()
    elif change == 'extra_metadata': manifest['raw_body'] = 'unapproved source'
    elif change == 'commit_authority':
        next(item for key, item in manifest['objects'].items() if '/commits/' in key)['value']['commit_object_preimage_verified'] = True
    elif change == 'file_budget':
        manifest['config']['budget']['max_files'] = 1
        manifest['config_cid'] = context.canonical_config_cid(manifest['config'], schema_version=context.SCHEMA)
    elif change == 'response_limit':
        extra = manifest['config']['budget']['max_response_bytes'] + 1 - manifest['attempts'][0]['response_bytes']
        manifest['attempts'][0]['response_bytes'] += extra; manifest['response_body_bytes'] += extra
    elif change == 'failure_status':
        manifest['attempts'][0]['status'] = 'http_error'; manifest['attempts'][0]['response_sha256'] = None
    else: manifest['response_body_bytes'] += 1
    raw = context._json(manifest); path.write_bytes(raw)
    with pytest.raises(ValueError): context.load_security_source_context(args['output'], expected_manifest_sha256=context._sha(raw))

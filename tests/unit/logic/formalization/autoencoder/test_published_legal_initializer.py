"""Published metadata is lineage, never authority to run or import remote state."""
from copy import deepcopy
import builtins
import hashlib
import json
from pathlib import Path
import os

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import published_legal_initializer as published
from tests.unit.logic.formalization.autoencoder.test_codebase_autoencoder_transfer import teacher, fork  # noqa: F401


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def metadata(teacher):
    manifest_path = 'checkpoints/20260630T221836Z/manifest.json'
    state_path = 'checkpoints/20260630T221836Z/state/legal-ir-autoencoder-canonical.state.json'
    state = {'relative_path': state_path, 'sha256': teacher[1], 'size_bytes': len(teacher[2]), 'source_count': 1}
    record = {'architecture': 'legacy_dense_v1', 'backend': 'authored_native_fixture', 'cycles': 3,
        'merge_weight': 1.0, 'metric_schema': None, 'path': '/never/read/this/remote/checkpoint',
        'run_id': 'authored_run', 'score': 0.5, 'state_schema': 'modal-autoencoder-state-v1', 'status': 'canonical_primary'}
    value = {'repo_id': published.REPO_ID, 'checkpoint_id': 'authored-canonical',
        'source_git_commit': 'b' * 40, 'canonical_state': state, 'source_records': [record],
        'files': [{'path': state_path, 'sha256': teacher[1], 'size_bytes': len(teacher[2])}]}
    return manifest_path, value, b'# Authored checkpoint metadata\n'


def _resolve(tmp_path, metadata, **overrides):
    manifest_path, value, readme = metadata
    raw = published._json(value)
    calls = []
    def fetch(url, maximum):
        calls.append((url, maximum))
        assert url.startswith(f'https://huggingface.co/datasets/{published.REPO_ID}/resolve/' + 'a' * 40 + '/')
        assert maximum == published.MAX_METADATA_BYTES
        if url.endswith('/' + manifest_path):
            return raw
        assert url.endswith('/README.md')
        return readme
    kwargs = dict(revision='a' * 40, manifest_path=manifest_path, expected_manifest_sha256=_sha(raw),
        expected_readme_sha256=_sha(readme), output=tmp_path / 'published-legal-source', fetch_bytes=fetch)
    kwargs.update(overrides)
    return published.resolve_published_legal_source(**kwargs), calls


@pytest.fixture
def source(tmp_path, metadata):
    return _resolve(tmp_path, metadata)[0]


@pytest.fixture
def binding(tmp_path, source, fork):
    return published.bind_published_legal_initializer(source=source,
        local_snapshot=Path(fork['output']) / 'source.checkpoint', initializer=fork,
        output=tmp_path / 'published-legal-binding')


def test_resolver_fetches_only_pinned_small_metadata_and_returns_portable_pin(tmp_path, metadata):
    source, calls = _resolve(tmp_path, metadata)
    pin = published.published_legal_source_pin(source)
    assert len(calls) == 2
    assert all('/state/' not in url for url, _ in calls)
    assert pin['source_records_sha256'] == _sha(published._json(metadata[1]['source_records']))
    assert '/never/read' not in json.dumps(pin)
    assert source['metadata_download_calls'] == source['checkpoint_download_calls'] == 0
    assert set(Path(source['output']).iterdir()) == {Path(source['output']) / p for p in ('manifest.json', 'README.md', 'source.json')}


def test_binding_replays_native_exact_rows_and_preserves_original_snapshot(teacher, fork, source, binding):
    before = teacher[0].read_bytes()
    value = published.validate_published_legal_initializer(expected_receipt=binding, replay_snapshot=True)
    assert value['selected_rows'] == 3 and value['embedding_width'] == 8
    assert value['snapshot_rehashed_now'] is True
    assert value['native_extraction_replayed_now'] is False
    assert value['authority'] == 'lineage_only'
    assert value['source_pin']['state_sha256'] == teacher[1]
    assert teacher[0].read_bytes() == before == teacher[2]
    record = json.loads(Path(binding['output'], 'binding.json').read_bytes())
    assert record['native_source_extraction_replayed'] is True
    assert record['legal_heads_transferred'] is record['code_domain_quality_established'] is False
    assert record['publisher_metrics_revalidated'] is record['proof_authority'] is False


def test_profile_validation_requires_neither_original_parent_nor_historical_imports(binding, fork, monkeypatch):
    Path(fork['output'], 'source.checkpoint').unlink()
    original = builtins.__import__
    def no_old_models(name, *args, **kwargs):
        if 'modal_autoencoder' in name or 'codebase_autoencoder_transfer' in name:
            raise AssertionError('historical model import during profile load')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_old_models)
    result = published.validate_published_legal_initializer(expected_receipt=binding)
    assert result['snapshot_rehashed_now'] is False
    with pytest.raises(FileNotFoundError):
        published.validate_published_legal_initializer(expected_receipt=binding, replay_snapshot=True)


@pytest.mark.parametrize('change', ['mutable_revision', 'manifest_traversal', 'wrong_pin', 'oversize', 'duplicate_json'])
def test_resolution_rejects_unpinned_or_unbounded_inputs(tmp_path, metadata, change):
    overrides = {}
    if change == 'mutable_revision': overrides['revision'] = 'main'
    if change == 'manifest_traversal': overrides['manifest_path'] = '../../manifest.json'
    if change == 'wrong_pin': overrides['expected_manifest_sha256'] = '0' * 64
    if change == 'oversize': overrides['fetch_bytes'] = lambda *_: b'x' * (published.MAX_METADATA_BYTES + 1)
    if change == 'duplicate_json':
        raw = b'{"repo_id":"ignored","repo_id":"' + published.REPO_ID.encode() + b'"}'
        overrides['fetch_bytes'] = lambda url, _: metadata[2] if url.endswith('README.md') else raw
        overrides['expected_manifest_sha256'] = _sha(raw)
    with pytest.raises(ValueError):
        _resolve(tmp_path, metadata, **overrides)
    assert not (tmp_path / 'published-legal-source').exists()


@pytest.mark.parametrize('change', ['different_file_hash', 'duplicate_file', 'path_escape', 'huge_state', 'boolean_count', 'unknown_record_field', 'nonfinite_score'])
def test_even_repinned_manifest_must_have_closed_consistent_parent_ledger(tmp_path, metadata, change):
    path, value, readme = deepcopy(metadata)
    if change == 'different_file_hash': value['files'][0]['sha256'] = '0' * 64
    if change == 'duplicate_file': value['files'].append(dict(value['files'][0]))
    if change == 'path_escape': value['files'][0]['path'] = '../../source'
    if change == 'huge_state': value['canonical_state']['size_bytes'] = value['files'][0]['size_bytes'] = published.MAX_SOURCE_BYTES + 1
    if change == 'boolean_count': value['canonical_state']['source_count'] = True
    if change == 'unknown_record_field': value['source_records'][0]['code'] = 'unexpected raw body'
    if change == 'nonfinite_score': value['source_records'][0]['score'] = float('nan')
    with pytest.raises(ValueError):
        _resolve(tmp_path, (path, value, readme))


@pytest.mark.parametrize('name', ['manifest.json', 'README.md', 'source.json'])
def test_metadata_drift_rejected_before_binding(source, name):
    path = Path(source['output']) / name
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError):
        published.published_legal_source_pin(source)


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'extra'])
def test_metadata_namespace_rejects_aliases_and_extra_files(source, tmp_path, kind):
    output = Path(source['output'])
    if kind == 'extra': (output / 'unapproved.py').write_bytes(b'')
    else:
        target = tmp_path / 'original-readme'
        (output / 'README.md').rename(target)
        if kind == 'symlink': (output / 'README.md').symlink_to(target)
        else: os.link(target, output / 'README.md')
    with pytest.raises(ValueError):
        published.published_legal_source_pin(source)


@pytest.mark.parametrize('kind', ['parent', 'wrong_snapshot_path', 'weights', 'binding', 'snapshot'])
def test_bound_parent_weights_and_evidence_drift_rejected(binding, fork, source, tmp_path, kind):
    if kind == 'wrong_snapshot_path':
        with pytest.raises(ValueError, match='exact retained'):
            published.bind_published_legal_initializer(source=source, local_snapshot=tmp_path / 'other',
                initializer=fork, output=tmp_path / 'second' / 'published-legal-binding')
        return
    name = {'parent': 'source.checkpoint', 'weights': 'initializer.json', 'snapshot': 'source.checkpoint', 'binding': 'binding.json'}[kind]
    output = binding['output'] if kind == 'binding' else fork['output']
    path = Path(output) / name
    path.chmod(0o644)
    raw = path.read_bytes()
    path.write_bytes((b'X' + raw[1:]) if kind == 'snapshot' else raw + b' ')
    with pytest.raises(ValueError):
        if kind == 'parent':
            published.bind_published_legal_initializer(source=source, local_snapshot=path, initializer=fork,
                output=tmp_path / 'second' / 'published-legal-binding')
        else:
            published.validate_published_legal_initializer(expected_receipt=binding, replay_snapshot=kind == 'snapshot')


def test_pinned_binding_cannot_silently_grant_code_or_proof_authority(binding):
    path = Path(binding['output']) / 'binding.json'
    value = json.loads(path.read_bytes())
    value['proof_authority'] = True
    raw = published._json(value)
    path.chmod(0o644)
    path.write_bytes(raw)
    repinned = {**binding, 'binding_sha256': _sha(raw)}
    with pytest.raises(ValueError, match='authority'):
        published.validate_published_legal_initializer(expected_receipt=repinned)


@pytest.mark.parametrize('root', ['source', 'initializer'])
def test_lineage_publication_cannot_add_files_inside_sealed_inputs(source, fork, root):
    directory = Path(source['output'] if root == 'source' else fork['output'])
    with pytest.raises(ValueError, match='outside'):
        published.bind_published_legal_initializer(source=source,
            local_snapshot=Path(fork['output']) / 'source.checkpoint', initializer=fork,
            output=directory / 'published-legal-binding')
    assert not (directory / 'published-legal-binding').exists()


@pytest.mark.parametrize('change', ['extra', 'boolean_dimension', 'domain'])
def test_binding_rejects_open_or_foreign_fork_descriptor(source, fork, tmp_path, change):
    foreign = dict(fork)
    if change == 'extra': foreign['legal_head'] = True
    if change == 'boolean_dimension': foreign['embedding_width'] = True
    if change == 'domain': foreign['domain'] = 'legal-ir'
    with pytest.raises(ValueError):
        published.bind_published_legal_initializer(source=source,
            local_snapshot=Path(fork['output']) / 'source.checkpoint', initializer=foreign,
            output=tmp_path / 'published-legal-binding')

"""Authored canonical CVE export contracts and explicitly pinned live artifacts."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import CVEFIXES_COLUMNS, CVEfixesRowAdapter
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit, DerivedDataset, PolicyCandidate, SourceRecord
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_cve_canonical_export as export


def _cid(value):
    return export.native._raw_sha256_cid(hashlib.sha256(value.encode()).digest())


def _raw_row():
    raw = {name: None for name in CVEFIXES_COLUMNS}
    raw.update(cve_id='CVE-2025-12345', hash='1' * 40,
        repo_url='https://github.com/authored-fixture/example',
        cve_description="[{'lang': 'en', 'value': 'Authored synthetic validation example.'}]",
        cwe_id='CWE-20', cwe_name='Improper Input Validation',
        file_paths=['src/check.py'], language='Python', security_keywords=[],
        vulnerable_code='def check(value):\n    return value\n',
        fixed_code='def check(value):\n    return max(value, 0)\n')
    return raw


def _exclusions(body_hash=None):
    return export.BenchmarkExclusions(source_families=('github.com/bottlepy/bottle',),
        file_names=('bottle.py',), code_sha256=(body_hash or '9' * 64,))


def _license():
    return {'dataset_id': export.CVEFIXES_DATASET_ID, 'source_revision': export.CVEFIXES_REVISION,
        'license_expression': 'Apache-2.0', 'evidence_url': 'https://example.invalid/authored-fixture',
        'review_status': 'reviewed', 'reviewed_by': 'Authored fixture only',
        'reviewed_at': '2026-09-29T00:00:00Z', 'redistribution_allowed': True}


def _selection(raw=None):
    raw = raw or _raw_row()
    row = CVEfixesRowAdapter().adapt(raw, row_index=17)
    return export.SelectedCVERow(export.canonical_source_row_cid(row), 17, raw['repo_url'],
        _cid('authored repository witness'), _cid('authored source shard'), 'data/train-00000-of-00003.parquet')


def _response(raw=None, **changes):
    return export._json({'rows': [{'row_idx': 17, 'row': raw or _raw_row(), 'truncated_cells': [], **changes}]})


def _fixture_export(tmp_path, monkeypatch):
    raw, pin = _raw_row(), export.HuggingFaceSourcePin(revision='2' * 40,
        manifest_sha256='3' * 64, release_root=_cid('authored release'))
    selection = _selection(raw)
    calls = []
    def select(**kwargs):
        return [selection], {'pin': pin.to_dict(), 'license_provenance': _license(),
            'native_control_receipt': {'authored_test_fixture': True},
            'routing_index_sha256': '4' * 64, 'graph_artifacts': []}
    monkeypatch.setattr(export, '_select_rows', select)
    def fetch(selected, maximum):
        calls.append((selected, maximum))
        return _response(raw)
    output = tmp_path / 'code-security-export'
    result = export.export_canonical_cve_training(metadata_root=tmp_path, data_root=tmp_path, pin=pin,
        graph_shards=('data/graph/nodes/part-000000.parquet',), repository_urls=(raw['repo_url'],),
        exclusions=_exclusions(), output=output, fetcher=fetch)
    return output, result, calls


def _repack(root, mutate):
    manifest = json.loads((root / 'manifest.json').read_bytes())
    pair_body = json.loads((root / 'training-pairs.json').read_bytes())
    mutate(manifest, pair_body)
    raw = export._json(pair_body)
    (root / 'training-pairs.json').write_bytes(raw)
    manifest['artifacts']['training-pairs.json'] = {'sha256': export._sha(raw), 'bytes': len(raw)}
    raw = export._json(manifest)
    (root / 'manifest.json').write_bytes(raw)
    return export._sha(raw)


def test_native_export_roundtrip_pairs_exact_code_inputs_with_audit_targets_without_bodies(tmp_path, monkeypatch):
    root, receipt, calls = _fixture_export(tmp_path, monkeypatch)
    loaded = export.load_canonical_cve_training(root, expected_manifest_sha256=receipt['manifest_sha256'])
    assert len(calls) == 1 and calls[0][1] == 1024 * 1024
    assert len(loaded['training_pairs']) == 2
    assert {type(record) for record in loaded['records']} >= {SourceRecord, CodeUnit, PolicyCandidate}
    assert loaded['manifest']['source_content_bound_to_pinned_revision'] is True
    assert loaded['manifest']['transport_revision_pinned'] is False
    assert loaded['manifest']['target_vocabulary'] == ['CWE-20']
    for pair in loaded['training_pairs']:
        body = _raw_row()[pair['polarity'] + '_code']
        assert pair['body_sha256'] == hashlib.sha256(body.encode()).hexdigest()
        assert pair['input']['ast_status'] == 'available'
        assert pair['input']['ast_samples']
        assert pair['input']['lexical_token_counts']['token:check'] == 1
        assert sum(pair['input']['lexical_token_counts'].values()) <= 40
        assert pair['target']['effect'] == 'audit'
        assert pair['target']['classification_only'] is True
        assert pair['target']['proof_authoritative'] is False
        assert pair['target']['exact_forbidden_action_resolved'] is False
    for path in root.iterdir():
        text = path.read_text()
        assert _raw_row()['vulnerable_code'] not in text and 'return max' not in text
        assert '"excerpt"' not in text
    assert all(record.payload.get('body_treatment') == 'digest_only'
               for record in loaded['records'] if isinstance(record, CodeUnit))


@pytest.mark.parametrize('repository', ['https://github.com/bottlepy/bottle', 'https://elsewhere.example/fork/BOTTLE.GIT'])
def test_bottle_family_exclusion_precedes_any_metadata_or_original_access(tmp_path, repository):
    with pytest.raises(export.CVETrainingSourceError, match='before original-row access'):
        export._select_rows(metadata_root=tmp_path / 'does-not-exist', data_root=tmp_path,
            pin=None, graph_shards=('data/graph/nodes/part-000000.parquet',),
            repository_urls=(repository,), exclusions=_exclusions())


@pytest.mark.parametrize('change', ['repository', 'index', 'truncation', 'cid', 'filename', 'empty_paths', 'extra_rows'])
def test_wrong_row_provenance_or_benchmark_overlap_rejected_before_projection(change):
    raw = _raw_row(); selection = _selection(raw); changes = {}
    if change == 'repository':
        raw['repo_url'] = 'https://github.com/bottlepy/bottle'
    elif change == 'index':
        changes['row_idx'] = 18
    elif change == 'truncation':
        changes['truncated_cells'] = ['fixed_code']
    elif change == 'cid':
        raw['fixed_code'] += '# changed source\n'
    elif change == 'filename':
        raw['file_paths'] = ['vendor/Bottle.py']
    elif change == 'empty_paths':
        raw['file_paths'] = []
    response = _response(raw, **changes)
    if change == 'extra_rows':
        body = json.loads(response); body['rows'] *= 2; response = export._json(body)
    with pytest.raises(ValueError):
        export._verified_row(response, selection, _exclusions())


def test_exact_body_hash_overlap_rejected_before_projection():
    raw = _raw_row()
    with pytest.raises(export.CVETrainingSourceError, match='code-body hash excluded'):
        export._verified_row(_response(raw), _selection(raw),
            _exclusions(hashlib.sha256(raw['fixed_code'].encode()).hexdigest()))


def test_original_row_transport_is_single_preselected_offset_and_bounded(monkeypatch):
    urls = []
    def open_one(url, timeout):
        urls.append(url)
        return io.BytesIO(_response())
    monkeypatch.setattr(export, 'urlopen', open_one)
    assert export.fetch_selected_cve_row(_selection()) == _response()
    assert 'offset=17' in urls[0] and 'length=1' in urls[0] and '/rows?' in urls[0]
    monkeypatch.setattr(export, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'x' * 12))
    with pytest.raises(export.CVETrainingSourceError, match='exceeds bound'):
        export.fetch_selected_cve_row(_selection(), 8)


@pytest.mark.parametrize('artifact', ['manifest.json', 'canonical-records.json', 'training-pairs.json'])
def test_export_artifact_tampering_is_detected(tmp_path, monkeypatch, artifact):
    root, receipt, _calls = _fixture_export(tmp_path, monkeypatch)
    with (root / artifact).open('ab') as handle:
        handle.write(b' ')
    with pytest.raises(export.CVETrainingSourceError, match='digest differs'):
        export.load_canonical_cve_training(root, expected_manifest_sha256=receipt['manifest_sha256'])


@pytest.mark.parametrize('kind', ['target', 'body_hash', 'source', 'polarity', 'lexical', 'projection', 'authority', 'vocabulary', 'raw_body'])
def test_rehashed_export_cannot_rebind_native_source_target_or_feature_contracts(tmp_path, monkeypatch, kind):
    root, _receipt, _calls = _fixture_export(tmp_path, monkeypatch)
    def mutate(manifest, pairs):
        pair = pairs['training_pairs'][0]
        if kind == 'target':
            pair['target']['effect'] = 'deny'
        elif kind == 'body_hash':
            pair['body_sha256'] = '0' * 64
        elif kind == 'source':
            pair['source_cid'] = _cid('foreign source')
        elif kind == 'polarity':
            pair['polarity'] = 'fixed' if pair['polarity'] == 'vulnerable' else 'vulnerable'
        elif kind == 'lexical':
            pair['input']['lexical_token_counts'] = {'token:unexpected': -1}
        elif kind == 'projection':
            pair['input']['projection_family'] = 'legal-ir'
        elif kind == 'authority':
            manifest['proof_authoritative'] = True
        elif kind == 'raw_body':
            pair['input']['source_text'] = 'unrequested original code body'
        else:
            manifest['target_vocabulary'] = ['CWE-999']
    digest = _repack(root, mutate)
    with pytest.raises(ValueError):
        export.load_canonical_cve_training(root, expected_manifest_sha256=digest)


def test_native_canonical_record_id_rechecked_even_after_artifact_hash_is_rebound(tmp_path, monkeypatch):
    root, _receipt, _calls = _fixture_export(tmp_path, monkeypatch)
    dataset = json.loads((root / 'canonical-records.json').read_bytes())
    code = next(record for record in dataset['records'] if record['record_type'] == 'code_unit')
    code['payload']['body_sha256'] = '0' * 64
    raw = export._json(dataset); (root / 'canonical-records.json').write_bytes(raw)
    manifest = json.loads((root / 'manifest.json').read_bytes())
    manifest['artifacts']['canonical-records.json'] = {'sha256': export._sha(raw), 'bytes': len(raw)}
    raw = export._json(manifest); (root / 'manifest.json').write_bytes(raw)
    with pytest.raises(ValueError):
        export.load_canonical_cve_training(root, expected_manifest_sha256=export._sha(raw))


def test_loader_rejects_extra_raw_files_and_symlink_artifacts(tmp_path, monkeypatch):
    root, receipt, _calls = _fixture_export(tmp_path, monkeypatch)
    extra = root / 'original-row.json'; extra.write_text('{}')
    with pytest.raises(export.CVETrainingSourceError, match='three public artifacts'):
        export.load_canonical_cve_training(root, expected_manifest_sha256=receipt['manifest_sha256'])
    extra.unlink()
    path = root / 'training-pairs.json'; moved = tmp_path / 'elsewhere.json'; path.rename(moved); path.symlink_to(moved)
    with pytest.raises(ValueError):
        export.load_canonical_cve_training(root, expected_manifest_sha256=receipt['manifest_sha256'])


@pytest.mark.parametrize('field', ['source_text', 'diff_header', 'unrecognized_text'])
def test_rehashed_native_source_payload_cannot_smuggle_original_code(tmp_path, monkeypatch, field):
    root, receipt, _calls = _fixture_export(tmp_path, monkeypatch)
    loaded = export.load_canonical_cve_training(root, expected_manifest_sha256=receipt['manifest_sha256'])
    original = next(record for record in loaded['records'] if isinstance(record, SourceRecord))
    changed = SourceRecord(source_cids=original.source_cids, parent_cids=original.parent_cids,
        config_cid=original.config_cid, source_uri=original.source_uri,
        source_revision=original.source_revision, row_key=original.row_key,
        payload={**dict(original.payload), field: 'unrequested original body content'})
    dataset = DerivedDataset(records=tuple(changed if record.cid == original.cid else record
                                          for record in loaded['records']))
    raw = dataset.canonical_bytes(); (root / 'canonical-records.json').write_bytes(raw)
    def mutate(manifest, pairs):
        manifest['canonical_dataset_cid'] = dataset.cid
        manifest['artifacts']['canonical-records.json'] = {'sha256': export._sha(raw), 'bytes': len(raw)}
        for pair in pairs['training_pairs']:
            if pair['source_record_cid'] == original.cid:
                pair['source_record_cid'] = changed.cid
    digest = _repack(root, mutate)
    with pytest.raises(export.CVETrainingSourceError, match='forbidden|closed native portable'):
        export.load_canonical_cve_training(root, expected_manifest_sha256=digest)


def test_unreviewed_license_does_not_create_canonical_training_rows():
    row = CVEfixesRowAdapter().adapt(_raw_row(), row_index=17)
    provenance = export.LicenseProvenance.from_dict({**_license(), 'review_status': 'unreviewed',
        'reviewed_by': '', 'reviewed_at': '', 'redistribution_allowed': False})
    with pytest.raises(export.CVETrainingSourceError, match='release policy rejected'):
        export._materialize_row(row, _selection(), provenance, _exclusions())


def test_existing_export_directory_is_never_overwritten(tmp_path):
    with pytest.raises(export.CVETrainingSourceError, match='fresh canonical export'):
        export.export_canonical_cve_training(metadata_root=tmp_path, data_root=tmp_path, pin=None,
            graph_shards=(), repository_urls=(), exclusions=_exclusions(), output=tmp_path)


def test_live_pinned_canonical_export_is_a_small_body_free_code_to_classification_dataset():
    value = os.environ.get('IPFS_CVE_CANONICAL_EXPORT_ROOT')
    digest = os.environ.get('IPFS_CVE_CANONICAL_EXPORT_SHA256')
    if not value or not digest:
        pytest.skip('explicit real canonical CVE export and immutable manifest hash required')
    loaded = export.load_canonical_cve_training(Path(value), expected_manifest_sha256=digest)
    assert loaded['manifest']['native_control_receipt']['verified'] is True
    assert loaded['manifest']['selected_rows']
    assert all(row['native_source_cid_preimage_verified'] for row in loaded['manifest']['selected_rows'])
    assert all('bottle' not in pair['source_family'] for pair in loaded['training_pairs'])
    assert len(loaded['training_pairs']) >= 2
    assert all((pair['input']['ast_status'] == 'available') == bool(pair['input']['ast_samples'])
               for pair in loaded['training_pairs'])
    assert all(pair['input']['lexical_token_counts'] for pair in loaded['training_pairs'])
    assert all(pair['target']['classification_only'] and not pair['target']['proof_authoritative']
               for pair in loaded['training_pairs'])

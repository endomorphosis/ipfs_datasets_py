"""Original-module ownership and optional real cached NumPy-head inference.

No training, downloads, source execution, provider calls or proof claims. The
native case requires explicitly supplied local checkpoint and GTE assets.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_numerical_selection_384 as owner
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseScanLimits, StaleCodebaseError


@pytest.fixture(scope='module')
def captured(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    root = tmp_path_factory.mktemp('numerical-selection-owner')
    repo = root/'repo'
    repo.mkdir()
    sources = {
        '00-unsupported.py': b'raise RuntimeError("target code must never execute")\ndef f(x): return x+1\n',
        '01-broken.py': b'def f(:\n',
        '02-empty.py': b'',
        '03-too-big.py': b'#' + b'x'*70000 + b'\n',
        '04-not-python.txt': b'declared public documentation\n',
        '10-select.py': b'import numpy as array_api\n\ndef choose_index(scores, buffer):\n    return array_api.argmax(scores)\n',
        '11-duplicate.py': b'import numpy as array_api\n\ndef choose_index(scores, buffer):\n    return array_api.argmax(scores)\n',
        '12-min.py': b'from numpy import argmin as select\ndef position(values, spare):\n    return select(values)\n',
        '13-over512.py': b'# '+ b'word '*900 + b'\nimport numpy as np\ndef index_of(values):\n    return np.argmax(values)\n',
    }
    for name, body in sources.items():
        (repo/name).write_bytes(body)
    for args in (('init', '-q'), ('config', 'user.name', 'Fixture'), ('config', 'user.email', 'fixture@example.invalid'),
            ('add', '.'), ('commit', '-qm', 'authored numerical source fixtures')):
        subprocess.run(['git', '-C', str(repo), *args], check=True)
    cx = duckdb.connect(str(root/'source.duckdb'), config={'threads': 1, 'memory_limit': '64MB'})
    store = DuckDBASTStore(connection=cx)
    cas = ImmutableCAS(root/'cas')
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
        catalog=CodebaseCatalog(store, cas))
    head = index.prepare_current(repo, repository_id='numerical-selection-fixture', operation_id='capture',
        expected_head=None, limits=CodebaseScanLimits(max_entries=16, max_file_bytes=1_048_576), memory_mb=512).head
    registry = AutoencoderRegistry(root/'models.duckdb', root/'models')
    value = SimpleNamespace(root=root, repo=repo, index=index, head=head, registry=registry, sources=sources)
    yield value
    value.registry.close()
    cx.close()


def _options(captured):
    return dict(expected_head=captured.head, paths=sorted(captured.sources))


def _assets():
    checkpoint = os.environ.get('NUMERICAL_SELECTION384_CHECKPOINT')
    snapshot = os.environ.get('CODEBASE384_EMBEDDING_SNAPSHOT')
    if not checkpoint or not snapshot:
        pytest.skip('explicit cached experimental checkpoint and pinned GTE snapshot required')
    return dict(checkpoint_path=checkpoint, checkpoint_sha256=owner.RELEASE['checkpoint_file_sha256'],
        embedding_snapshot=snapshot)


def test_full_original_source_population_and_all_deferrals(captured):
    prepared = owner.prepare_numerical_selection(captured.index, **_options(captured))
    assert prepared['counts'] == dict(files=9, eligible_files=4, selected_units=4)
    files = {f['path']: f for f in prepared['files']}
    assert files['00-unsupported.py']['disposition'] == 'unsupported_profile'
    assert files['01-broken.py']['disposition'] == 'unsupported_profile'
    assert files['02-empty.py']['disposition'] == 'deferred_source_byte_limit'
    assert files['03-too-big.py']['disposition'] == 'deferred_source_byte_limit'
    assert files['04-not-python.txt']['disposition'] == 'unsupported_profile'
    for row in prepared['selected_inputs']:
        assert set(row) == {'path', 'unit_id', 'source_text'}
        assert row['source_text'].encode() == captured.sources[row['path']]
        assert files[row['path']]['unit']['model_input_text'] == row['source_text']
        assert files[row['path']]['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
    # One content-identical pair retains distinct source locations/units.
    assert files['10-select.py']['unit']['unit_id'] != files['11-duplicate.py']['unit']['unit_id']
    assert all((captured.repo/name).read_bytes() == body for name, body in captured.sources.items())
    assert all(type(prepared[k]) is type(v) and prepared[k] == v for k, v in owner.FALSE.items())


@pytest.mark.parametrize('paths', [[], ['../escape.py'], ['/absolute.py'], ['10-select.py', '10-select.py'],
    ['./10-select.py'], ['10-select.py/'], ['no-such-file.py'], ['10-select.py'] * 257])
def test_bad_or_outside_captured_paths_refused(captured, paths):
    with pytest.raises(ValueError):
        owner.prepare_numerical_selection(captured.index, expected_head=captured.head, paths=paths)


def test_selection_budget_counts_eligible_not_early_unsupported(captured, monkeypatch):
    monkeypatch.setattr(owner, 'MAX_SELECTED', 2)
    prepared = owner.prepare_numerical_selection(captured.index, **_options(captured))
    assert [r['path'] for r in prepared['selected_inputs']] == ['10-select.py', '11-duplicate.py']
    assert prepared['counts'] == dict(files=9, eligible_files=4, selected_units=2)
    assert [f['path'] for f in prepared['files'] if f['disposition'] == 'deferred_selection_budget'] == [
        '12-min.py', '13-over512.py']


def test_exact_release_loader_keeps_raw_and_canonical_identity_separate(tmp_path):
    assets = _assets()
    path, checkpoint = owner._checkpoint(assets['checkpoint_path'], assets['checkpoint_sha256'])
    assert path == str(Path(assets['checkpoint_path']).absolute())
    assert checkpoint['parent_sha256'] == owner.RELEASE['parent_sha256']
    assert owner.profile._digest(checkpoint) != assets['checkpoint_sha256']
    body = Path(path).read_bytes()
    assert len(body) == owner.RELEASE['checkpoint_bytes']
    bad = tmp_path/'changed.json'
    bad.write_bytes(body[:-1] + (b' ' if body[-1:] != b' ' else b'\n'))
    with pytest.raises(ValueError, match='digest differs'):
        owner._checkpoint(bad, assets['checkpoint_sha256'])
    with pytest.raises(ValueError, match='published numerical checkpoint'):
        owner._checkpoint(path, '0'*64)
    link = tmp_path/'linked.json'
    link.symlink_to(path)
    with pytest.raises((OSError, ValueError)):
        owner._checkpoint(link, assets['checkpoint_sha256'])
    parent = tmp_path/'linked-directory'
    parent.symlink_to(Path(path).parent, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        owner._checkpoint(parent/Path(path).name, assets['checkpoint_sha256'])
    copied = tmp_path/'hardlinked.json'
    copied.write_bytes(body)
    os.link(copied, tmp_path/'second-name.json')
    with pytest.raises(ValueError, match='regular numerical checkpoint'):
        owner._checkpoint(copied, assets['checkpoint_sha256'])


@pytest.fixture(scope='module')
def native(captured):
    assets = _assets()
    result = owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
        **_options(captured), **assets, timeout_seconds=180, memory_mb=4096)
    return result, assets


def test_actual_cpu_inference_retains_tokens_predictions_and_original_source(native, captured):
    result, assets = native
    assert result['native_worker_executed'] and result['inference_executed']
    report = result['report']
    rows = report['output']['rows']
    assert len(rows) == 4
    assert report['output']['model_loads'] == 1
    assert report['worker_receipt']['provider_calls'] == 0
    assert report['worker_receipt']['device'] == 'cpu'
    assert report['coverage']['token_deferred'] == 1
    assert report['coverage']['source_aligned_fragments'] + report['coverage']['source_mismatches'] == 3
    assert report['coverage']['file_dispositions']['unsupported_profile'] == 3
    assert report['retention'] == 'unknown_not_evaluated'
    receipt = report['output']['embedding_receipt']
    assert receipt['execution']['kind'] == 'native' and receipt['execution']['truncation'] is False
    assert receipt['status_counts'] == dict(embedded=2, token_limit_exceeded=1, missing_input=0)
    assert len(receipt['inputs']) == 3
    assert all(i['source']['source_kind'] == 'diagnostic' for i in receipt['inputs'])
    assert rows[-1]['tokens'] > 512 and rows[-1]['candidate'] is None
    assert rows[-1]['status'] == 'deferred_gte_token_limit'
    assert rows[0]['embedding_input_id'] == rows[1]['embedding_input_id']
    for row in rows[:-1]:
        assert row['candidate']['source_sha256'] == hashlib.sha256(captured.sources[row['path']]).hexdigest()
        assert row['candidate']['candidate_replaced'] is False
        assert row['candidate']['source_obligations_discharged'] == 0
    assert report['key']['checkpoint_file_sha256'] == assets['checkpoint_sha256']
    assert report['key']['checkpoint_canonical_sha256'] == report['output']['inference']['checkpoint_sha256']
    assert all((captured.repo/name).read_bytes() == body for name, body in captured.sources.items())


def test_cold_native_operation_replay_never_embeds_or_decodes(native, captured, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    result, assets = native
    def forbidden(*args, **kwargs):
        pytest.fail('immutable native receipt replay invoked a model')
    monkeypatch.setattr(owner, '_worker', forbidden)
    monkeypatch.setattr(owner.embeddings, 'produce_native_embedding_receipt', forbidden)
    monkeypatch.setattr(owner.profile.NumericalSelectionRuntime384, 'infer', forbidden)
    captured.registry.close()
    captured.registry = AutoencoderRegistry(captured.root/'models.duckdb', captured.root/'models')
    again = owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
        **_options(captured), **assets)
    assert not again['native_worker_executed'] and not again['inference_executed']
    assert again['artifact'] == result['artifact'] and again['report'] == result['report']
    assert owner.validate_numerical_selection(captured.index, captured.repo, result,
        registry=captured.registry, **assets) == result


@pytest.mark.parametrize('damage', ['raw_hash', 'canonical_hash', 'source', 'candidate', 'authority', 'zero_bool',
    'token', 'vector', 'receipt_kind', 'projection', 'coverage', 'omission', 'operation'])
def test_changed_retained_or_uncommitted_evidence_refused(native, captured, damage):
    result, assets = native
    bad = deepcopy(result)
    report = bad['report']
    if damage == 'raw_hash':
        report['key']['checkpoint_file_sha256'] = '0'*64
    elif damage == 'canonical_hash':
        report['key']['checkpoint_canonical_sha256'] = '0'*64
    elif damage == 'source':
        report['preparation']['selected_inputs'][0]['source_text'] += '# unbound edit\n'
    elif damage == 'candidate':
        report['output']['rows'][0]['candidate']['candidate_replaced'] = True
    elif damage == 'authority':
        report['proof_authority'] = True
    elif damage == 'zero_bool':
        report['source_obligations_discharged'] = False
    elif damage == 'token':
        report['output']['rows'][-1]['tokens'] = 512
    elif damage == 'vector':
        report['output']['embedding_receipt']['results'][0]['vector']['bits'] = '0'*3072
    elif damage == 'receipt_kind':
        report['output']['embedding_receipt']['execution']['kind'] = 'injected_fixture'
    elif damage == 'projection':
        row = report['output']['rows'][0]['candidate']
        row['matched_projection_refs'] = dict(family_artifact_ids=['made-up'])
    elif damage == 'coverage':
        report['coverage']['token_deferred'] = 0
    elif damage == 'omission':
        report['output']['rows'].pop()
    else:
        report['retention'] = 'forged_uncommitted_report'
        bad['artifact'] = owner.shared._stage(captured.registry, report)
    with pytest.raises(ValueError):
        owner.validate_numerical_selection(captured.index, captured.repo, bad,
            registry=captured.registry, **assets)


def test_changed_current_source_refused_before_model(native, captured, monkeypatch):
    result, assets = native
    monkeypatch.setattr(owner, '_worker', lambda *a, **k: pytest.fail('stale source reached model'))
    path = captured.repo/'10-select.py'
    original = path.read_bytes()
    try:
        path.write_bytes(original + b'# changed after captured inference\n')
        with pytest.raises(StaleCodebaseError):
            owner.validate_numerical_selection(captured.index, captured.repo, result,
                registry=captured.registry, **assets)
        with pytest.raises(StaleCodebaseError):
            owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
                **_options(captured), **assets)
    finally:
        path.write_bytes(original)


def test_no_supported_modules_never_invokes_embedding(captured):
    assets = _assets()
    result = owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
        expected_head=captured.head, paths=['00-unsupported.py', '01-broken.py'], **assets)
    assert result['native_worker_executed'] and not result['inference_executed']
    assert result['report']['output']['model_loads'] == 0
    assert result['report']['output']['rows'] == []
    assert result['report']['output']['embedding_receipt'] is None
    assert result['report']['output']['inference'] is None


def test_explicit_long_formalization_budget_preserves_cold_replay(native, captured, monkeypatch):
    result, assets = native
    def forbidden(*args, **kwargs):
        pytest.fail('long-budget replay invoked a model')
    monkeypatch.setattr(owner, '_worker', forbidden)
    for profile, timeout in ((None, 601), ('unrecognized-profile', 180),
            (owner.shared.FORMALIZATION_BUDGET_PROFILE, 3601)):
        with pytest.raises(ValueError):
            owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
                **_options(captured), **assets, timeout_seconds=timeout, budget_profile=profile)
        with pytest.raises(ValueError):
            owner.validate_numerical_selection(captured.index, captured.repo, result,
                registry=captured.registry, **assets, timeout_seconds=timeout, budget_profile=profile)
    again = owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
        **_options(captured), **assets, timeout_seconds=1800, budget_profile=owner.shared.FORMALIZATION_BUDGET_PROFILE)
    assert again['report'] == result['report'] and not again['native_worker_executed']
    assert owner.validate_numerical_selection(captured.index, captured.repo, result,
        registry=captured.registry, **assets, timeout_seconds=1800,
        budget_profile=owner.shared.FORMALIZATION_BUDGET_PROFILE) == result


def test_already_cancelled_attempt_never_enters_worker(native, captured, monkeypatch):
    from threading import Event
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    result, assets = native
    monkeypatch.setattr(owner, '_worker', lambda *a, **k: pytest.fail('cancelled attempt reached worker'))
    cancelled = Event()
    cancelled.set()
    with pytest.raises(LeaseCancelledError):
        owner.infer_numerical_selection(captured.index, captured.repo, registry=captured.registry,
            **_options(captured), **assets, cancel_event=cancelled)
    with pytest.raises(LeaseCancelledError):
        owner.validate_numerical_selection(captured.index, captured.repo, result,
            registry=captured.registry, **assets, cancel_event=cancelled)

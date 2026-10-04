"""Actual retained-vector parity, stage provenance and fail-closed inputs.

Integration checks reuse local native receipts and frozen weights; no encoder
inference or training is performed. They skip when those retained files are not
installed. Synthetic producer claims are only used as rejection fixtures.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as subject


ARTIFACTS = Path('/home/barberb/lift_coding/artifacts')
PACKAGE = ARTIFACTS / 'ir-384-hub-release-20261002/packages/legal_ir/checkpoint.json'
PACKAGE_SHA = '26cb6d77947b5b8e1e6c08e68ff8c6ce1c8f23002d56bfc1ebbd024c55a0c2da'
RECEIPT = ARTIFACTS / 'legal-decoder-structured-retrieval-20261002/prepared/source-embedding-production-000.json'


def reference(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


@pytest.fixture(scope='module')
def retained():
    if not PACKAGE.is_file() or not RECEIPT.is_file():
        pytest.skip('retained Legal384 package and native production receipt unavailable')
    torch = pytest.importorskip('torch')
    if str(torch.__version__) != '2.13.0+cu130':
        pytest.skip('saved package requires its strict original Torch runtime')
    data = json.loads(RECEIPT.read_text())
    sources = [{'id': f'actual-parity-{index}', 'source_text': item['text']}
               for index, item in enumerate(data['inputs'][:2])]
    refs = [reference(RECEIPT)]
    rows = subject.embedding_rows(sources, embedding_receipts=refs)
    bundle = subject.vectorize(rows, package_path=PACKAGE, package_sha256=PACKAGE_SHA,
                               embedding_receipts=refs)
    return sources, rows, refs, bundle


def resign(bundle):
    for row in bundle['rows']:
        for entry in row['stages'].values():
            r = entry['receipt']
            r['receipt_sha256'] = subject.digest({k: v for k, v in r.items() if k != 'receipt_sha256'})
    bundle['bundle_sha256'] = subject.digest({k: v for k, v in bundle.items() if k != 'bundle_sha256'})


def test_three_stages_equal_actual_saved_implementations(retained):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula import LatentFormulaDecoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_autoencoder import _cpu
    sources, rows, _, bundle = retained
    with _cpu():
        runtime = legal_384_package.load_package(PACKAGE, expected_sha256=PACKAGE_SHA)
        samples = legal_384_package._rows(rows, runtime._payload['embedding_contract'])
        core = [joint.raw_projection(runtime.model, sample) for sample in samples]
        head = LatentFormulaDecoder(runtime._payload['formula_checkpoint'],
                                    expected_binding=runtime._payload['core_binding'])
        trained = head.project(core)
    for stage, expected in [('raw384', [r['embedding'] for r in rows]), ('core384', core), ('trained384', trained)]:
        records = subject.stage_rows(bundle, stage=stage, sources=sources)
        assert [r['vector'] for r in records] == expected
        assert all(r['stage'] == stage for r in records)
    assert rows[0]['embedding'] != core[0] != trained[0]
    assert not bundle['encoder_inference_executed'] and not bundle['training_executed']
    assert bundle['core_state_unchanged'] and not bundle['target_access']
    assert reference(PACKAGE)['sha256'] == PACKAGE_SHA


def test_cache_reuse_never_invokes_encoder(retained, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
    sources, rows, refs, _ = retained
    def forbidden(*args, **kwargs):
        pytest.fail('cached native embeddings must not be regenerated')
    monkeypatch.setattr(runtime, 'produce_native_embedding_receipt', forbidden)
    assert subject.embedding_rows(sources, embedding_receipts=refs) == rows


@pytest.mark.parametrize('change', ['target', 'wrong_dimension', 'vector_substitution'])
def test_reject_target_fields_wrong_dimensions_and_fake_native_vectors(retained, change):
    _, rows, refs, _ = retained
    rows = deepcopy(rows)
    if change == 'target':
        rows[0]['canonical_ir'] = {'rules': []}
    elif change == 'wrong_dimension':
        rows[0]['embedding'] = rows[0]['embedding'][:8]
    else:
        rows[0]['embedding'] = list(reversed(rows[0]['embedding']))
    with pytest.raises(ValueError):
        subject.vectorize(rows, package_path=PACKAGE, package_sha256=PACKAGE_SHA, embedding_receipts=refs)


@pytest.mark.parametrize('change', ['injected', 'producer', 'assets'])
def test_reject_relabelled_fixture_or_encoder_identity(retained, tmp_path, change):
    sources, _, _, _ = retained
    data = json.loads(RECEIPT.read_text())
    if change == 'injected':
        data['execution']['kind'] = 'injected_fixture'
    elif change == 'producer':
        data['producer']['code_sha256'] = '0' * 64
    else:
        data['model_assets'][0]['sha256'] = '0' * 64
    path = tmp_path / 'modified-receipt.json'
    path.write_bytes(subject._wire(data))
    with pytest.raises(ValueError):
        subject.embedding_rows(sources, embedding_receipts=[reference(path)])


def test_new_source_cannot_borrow_existing_vector(retained):
    sources, rows, refs, _ = retained
    wrong = deepcopy(rows)
    wrong[0]['source_text'] += ' Additional condition.'
    with pytest.raises(ValueError, match='source-bound'):
        subject.vectorize(wrong, package_path=PACKAGE, package_sha256=PACKAGE_SHA, embedding_receipts=refs)
    with pytest.raises(ValueError, match='no successful native'):
        subject.embedding_rows([{'id': 'missing', 'source_text': 'An uncached source.'}], embedding_receipts=refs)


@pytest.mark.parametrize('change', ['stage', 'kind', 'target', 'dimension', 'source', 'producer'])
def test_consumer_rejects_stage_confusion_even_with_updated_hashes(retained, change):
    sources, _, _, original = retained
    bundle = deepcopy(original)
    record = bundle['rows'][0]['stages']['core384']
    if change == 'stage':
        record['receipt']['stage'] = 'raw384'
    elif change == 'kind':
        record['receipt']['evidence']['kind'] = 'native_gte_source_embedding'
    elif change == 'target':
        record['receipt']['evidence']['canonical_ir'] = {'rules': []}
    elif change == 'dimension':
        record['receipt']['dimension'] = 8
    elif change == 'source':
        record['receipt']['source_sha256'] = '0' * 64
    else:
        bundle['producer_pins'][str(Path(subject.__file__).resolve())] = '0' * 64
    resign(bundle)
    with pytest.raises(ValueError):
        subject.stage_rows(bundle, stage='core384', sources=sources)


def test_consumer_rejects_incomplete_source_coverage(retained):
    sources, _, _, bundle = retained
    with pytest.raises(ValueError, match='coverage'):
        subject.stage_rows(bundle, stage='raw384', sources=sources[:1])
    with pytest.raises(ValueError, match='source identity'):
        subject.stage_rows(bundle, stage='raw384', sources=list(reversed(sources)))


def test_historical8_uses_real_feature_profile_without_reconstruction(monkeypatch):
    pytest.importorskip('spacy')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic
    def forbidden(*args, **kwargs):
        pytest.fail('historical feature production must not call learned reconstruction')
    monkeypatch.setattr(linguistic.LinguisticAutoencoder, 'encode', forbidden)
    monkeypatch.setattr(linguistic.LinguisticAutoencoder, 'decode', forbidden)
    sources = [{'id': 'historical-a', 'source_text': 'The clerk shall submit the report.'}]
    bundle = subject.historical_features(sources)
    rows = subject.stage_rows(bundle, stage=subject.HISTORICAL_STAGE, sources=sources)
    assert len(rows[0]['vector']) == 8
    evidence = bundle['rows'][0]['stages'][subject.HISTORICAL_STAGE]['receipt']['evidence']
    assert evidence['kind'] == 'deterministic_linguistic_feature_hash'
    assert not evidence['learned_reconstruction_checkpoint_used']
    assert not evidence['pretrained_semantic_encoder_used']
    assert not bundle['target_aware_reconstruction_used'] and not bundle['sample_memory_used']
    with pytest.raises(ValueError):
        subject.stage_rows(bundle, stage='raw384', sources=sources)

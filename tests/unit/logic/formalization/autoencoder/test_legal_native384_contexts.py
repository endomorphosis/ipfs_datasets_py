"""Saved-record contract tests, using explicitly authored producer records.

No model runs. Native-shaped fixtures exercise receipt parsing and source joins;
their acceptance is artifact consistency, never execution attestation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_native384_contexts as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def records(tmp_path, *, partial=False):
    sources, inputs, paths = [], [], {}
    for index, text in enumerate(('The agency shall disclose records.', 'The board may retain notices.')):
        source_bytes = text.encode()
        prefix = b'prefix\n' if partial else b''
        raw = prefix + source_bytes
        artifact = SourceArtifact(sha(raw), len(raw))
        source = SourceSpan(artifact, 'us_code', 'fictional', str(index), 'en', 'fixture',
                            len(prefix), len(raw))
        inputs.append(codec.EmbeddingInput(source, 'fictional', str(index), text, 'fixture'))
        path = tmp_path / f'source-{index}.txt'
        path.write_bytes(raw)
        paths[artifact.sha256] = path
        sources.append({'id': 'fictional-' + str(index), 'source_text': text})
    resolver = lambda ref: paths[ref['sha256']]
    receipt = codec.build_embedding_production_receipt(inputs,
        results=[{'input_id': item.input_id, 'status': 'embedded',
            'tokens': {'input_ids': [101, 2000 + index, 102], 'attention_mask': [1, 1, 1], 'token_type_ids': [0, 0, 0]},
            'vector': [1. if index == 0 else -1.] + [0.] * 383} for index, item in enumerate(inputs)],
        execution=codec.native_execution_profile(),
        model_assets=[{'name': name, 'bytes': size, 'sha256': digest}
                      for name, (size, digest) in sorted(runtime._PINNED_ASSETS.items())],
        producer={'code_sha256': sha(Path(runtime.__file__).read_bytes()),
            'runtime_versions': {name: 'fixture' for name in ('python', 'torch', 'transformers', 'sentence_transformers', 'tokenizers')}},
        resolver=resolver)
    reference = save(tmp_path / 'producer.json', receipt.to_dict())
    evidence = {'stage': 'raw384', 'embedding_receipts': [reference], 'bundle': None}
    return sources, evidence, resolver


@pytest.fixture
def retained(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline inspection invoked numerical producer')
    monkeypatch.setattr(runtime, 'produce_native_embedding_receipt', forbidden)
    monkeypatch.setattr(native, 'vectorize', forbidden)
    return records(tmp_path)


def test_actual_receipt_codec_joins_source_vector_and_preserves_order(retained):
    sources, evidence, _ = retained
    before = deepcopy((sources, evidence))
    result = subject.verify_native384_contexts(evidence, sources=sources)
    assert [r['context'][0] for r in result['contexts']] == [1., -1.]
    assert result['inspection']['verification_scope'] == 'saved_native_source_vector_rejoin'
    assert result['inspection']['runtime_computation_proven'] is False
    assert result['inspection']['projection_reexecuted'] is False
    assert result['representation']['dimension'] == 384
    assert (sources, evidence) == before
    result['contexts'][0]['context'][0] = 99.
    assert subject.verify_native384_contexts(evidence, sources=sources)['contexts'][0]['context'][0] == 1.


def test_partial_source_requires_original_artifact_resolver(tmp_path):
    sources, evidence, resolver = records(tmp_path, partial=True)
    with pytest.raises(ValueError, match='resolver'):
        subject.verify_native384_contexts(evidence, sources=sources)
    result = subject.verify_native384_contexts(evidence, sources=sources, source_resolver=resolver)
    assert len(result['contexts']) == 2


@pytest.mark.parametrize('damage', ['text', 'target', 'duplicate', 'empty', 'stage', 'extra'])
def test_source_and_evidence_contracts_reject_unsupported_inputs(retained, damage):
    sources, evidence, _ = retained
    if damage == 'text': sources[0]['source_text'] += ' replaced'
    elif damage == 'target': sources[0]['canonical_ir'] = {}
    elif damage == 'duplicate': sources.append(deepcopy(sources[0]))
    elif damage == 'empty': sources.clear()
    elif damage == 'stage': evidence['stage'] = 'native768'
    else: evidence['verified'] = True
    with pytest.raises(ValueError):
        subject.verify_native384_contexts(evidence, sources=sources)


@pytest.mark.parametrize('damage', ['injected', 'producer', 'assets'])
def test_rehashed_ineligible_native_claims_are_rejected(retained, damage):
    sources, evidence, _ = retained
    reference = evidence['embedding_receipts'][0]
    payload = json.loads(Path(reference['path']).read_bytes())
    if damage == 'injected': payload['execution']['kind'] = 'injected_fixture'
    elif damage == 'producer': payload['producer']['code_sha256'] = 'a' * 64
    else: payload['model_assets'][0]['sha256'] = 'a' * 64
    evidence['embedding_receipts'][0] = save(Path(reference['path']), payload)
    with pytest.raises(ValueError):
        subject.verify_native384_contexts(evidence, sources=sources)


def test_receipt_change_is_detected_even_with_retained_context_input(retained):
    sources, evidence, _ = retained
    subject.verify_native384_contexts(evidence, sources=sources)
    Path(evidence['embedding_receipts'][0]['path']).write_text('{}')
    with pytest.raises(ValueError):
        subject.verify_native384_contexts(evidence, sources=sources)


def derived_fixture(retained, tmp_path, monkeypatch):
    sources, evidence, resolver = retained
    # This package is a custody fixture only; the verifier does not load it.
    package_ref = save(tmp_path / 'package.json', {'fictional_custody_fixture': True})
    package = {k: package_ref[k] for k in ('path', 'sha256')}
    package.update(core_binding={'dimension': 384}, core_state_sha256='a' * 64,
                   formula_checkpoint_sha256='b' * 64, projection_optimizer_steps=1)
    index = native._native_index(evidence['embedding_receipts'], resolver)
    pins = {'explicit_stage_validator_fixture': 'c' * 64}
    monkeypatch.setattr(native, 'producer_pins', lambda: deepcopy(pins))
    rows = []
    for source in sources:
        source_sha = sha(source['source_text'].encode())
        raw, upstream = index[(source_sha, source['source_text'])][0]
        core, trained = [v * 2 for v in raw], [v * 3 for v in raw]
        parser = dict(source_sha256=source_sha, sample_sha256='d' * 64, modal_ir_sha256='e' * 64,
            parser_trace={}, construction='fixture', features_origin='source_parser_not_canonical_targets')
        common = dict(identity=source['id'], source_sha=source_sha)
        stages = {'raw384': native._stage('raw384', raw, upstream=None,
            evidence={'kind': 'native_gte_source_embedding', 'native': upstream}, **common)}
        for name, vector, previous, kind in [('core384', core, raw, 'source_parser_sparse_core_projection'),
            ('trained384', trained, core, 'saved_learned_residual_projection')]:
            stages[name] = native._stage(name, vector, upstream=native.digest(previous),
                evidence={'kind': kind, 'native': upstream, 'parser': parser, 'package': package}, **common)
        rows.append({'id': source['id'], 'source_sha256': source_sha, 'stages': stages})
    bundle = dict(schema=native.SCHEMA, stages=list(native.STAGES), package=package, producer_pins=pins,
        producer_pin_scope='explicit fixture', rows=rows, encoder_inference_executed=False,
        cached_native_embeddings_consumed=True, core_state_unchanged=True, training_executed=False, **native._FALSE)
    bundle['bundle_sha256'] = native.digest(bundle)
    return bundle


@pytest.mark.parametrize('stage', ['core384', 'trained384'])
def test_saved_derived_custody_keeps_weaker_scope_explicit(retained, tmp_path, monkeypatch, stage):
    sources, evidence, _ = retained
    bundle = derived_fixture(retained, tmp_path, monkeypatch)
    evidence.update(stage=stage, bundle=save(tmp_path / 'bundle.json', bundle))
    result = subject.verify_native384_contexts(evidence, sources=sources)
    assert result['contexts'][0]['context'][0] == (2. if stage == 'core384' else 3.)
    assert result['inspection']['verification_scope'] == 'saved_derived_projection_custody_only'
    assert result['inspection']['derived_projection_computation_verified'] is False
    assert result['inspection']['saved_package_bytes_verified'] is True


def test_rehashed_derived_bundle_cannot_substitute_original_raw_vector(retained, tmp_path, monkeypatch):
    sources, evidence, _ = retained
    bundle = derived_fixture(retained, tmp_path, monkeypatch)
    row = bundle['rows'][0]
    row['stages']['raw384']['vector'][0] = 9.
    raw = row['stages']['raw384']
    raw['receipt']['vector_sha256'] = native.digest(raw['vector'])
    row['stages']['core384']['receipt']['upstream_vector_sha256'] = native.digest(raw['vector'])
    for entry in row['stages'].values():
        r = entry['receipt']
        r['receipt_sha256'] = native.digest({k: v for k, v in r.items() if k != 'receipt_sha256'})
    bundle['bundle_sha256'] = native.digest({k: v for k, v in bundle.items() if k != 'bundle_sha256'})
    evidence.update(stage='trained384', bundle=save(tmp_path / 'bundle.json', bundle))
    with pytest.raises(ValueError, match='rejoin'):
        subject.verify_native384_contexts(evidence, sources=sources)


def test_original_native384_records_reach_public_batch_consumer(retained):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_context_binding as binding
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import CheckpointContentGuard
    digest = lambda value: CheckpointContentGuard(value).sha256
    sources, evidence, _ = retained
    source = sources[0]
    rows = [{**source, 'canonical_ir': {'rules': [{'modality': 'O', 'actor': 'agency',
        'action': 'disclose', 'object': 'records', 'conditions': [], 'exceptions': [], 'temporal': []}]}}]
    manifest = splits.LegalIRSplitManifest(
        examples=(splits.LegalIRSplitExample.from_sample({'sample_id': source['id'], 'text': source['source_text']}),),
        assignments={source['id']: 'train'}, config_digest='a' * 64).to_dict()
    exact = dict(id=source['id'], source_text_sha256=sha(source['source_text'].encode()),
                 canonical_ir_sha256=digest(rows[0]['canonical_ir']))
    eligibility = [{**exact, 'target_origin': 'authored_engineering_fixture', 'status': 'eligible',
        'allowed_operations': ['training'], 'reason': 'Fictional producer-to-consumer artifact fixture.'}]
    exposure = [{**exact, 'target_exposure': 'declared_supervised_training', 'provenance_ref': 'fixture:authored'}]
    contexts = subject.verify_native384_contexts(evidence, sources=[source])['contexts']
    common = dict(split_manifest=manifest, eligibility_records=eligibility, exposure_records=exposure,
                  contexts=contexts, context_evidence=evidence)
    prepared = binding.prepare_source_span_context_binding(rows, **common,
        expected_rows_sha256=digest(rows), expected_split_manifest_sha256=digest(manifest),
        expected_eligibility_sha256=digest(eligibility), expected_exposure_sha256=digest(exposure),
        expected_contexts_sha256=digest(contexts), expected_context_evidence_sha256=digest(evidence),
        operation='training', stage='raw384')
    received = []
    binding.consume_source_span_context_binding(prepared, rows, **common, consumer=received.append)
    assert received == [[{**rows[0], 'latent': contexts[0]['context']}]]
    assert prepared.receipt()['context_verification']['inspection']['runtime_computation_proven'] is False

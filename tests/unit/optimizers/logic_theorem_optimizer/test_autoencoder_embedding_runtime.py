"""Offline producer boundaries using explicit diagnostic tensors, never weights."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan


class FixtureModel:
    """A conspicuous diagnostic model; it never enters the native constructor."""
    def __init__(self, *, drift=False, dtype=torch.float32, nonfinite=False):
        self.calls = []
        self.drift = drift
        self.dtype = dtype
        self.nonfinite = nonfinite

    def tokenizer(self, text, **kwargs):
        assert kwargs["truncation"] is False
        assert kwargs["add_special_tokens"] is True
        assert kwargs["padding"] is False
        ids = [101] + [1000 + sum(word.encode()) % 1000 for word in text.split()] + [102]
        return {"input_ids": ids, "attention_mask": [1] * len(ids), "token_type_ids": [0] * len(ids)}

    def tokenize(self, texts):
        rows = [self.tokenizer(text, truncation=False, add_special_tokens=True, padding=False) for text in texts]
        width = max(len(row["input_ids"]) for row in rows)
        result = {key: torch.tensor([row[key] + [0] * (width - len(row[key])) for row in rows], dtype=torch.long)
                  for key in ("input_ids", "attention_mask", "token_type_ids")}
        if self.drift:
            result["input_ids"][0, 1] += 1
        return {**result, "modality": "text"}

    def __call__(self, features):
        assert torch.is_inference_mode_enabled()
        self.calls.append(features["input_ids"].clone())
        vectors = torch.zeros((len(features["input_ids"]), 384), dtype=self.dtype)
        vectors[:, 0] = float("nan") if self.nonfinite else 1.0
        return {**features, "sentence_embedding": vectors}


def _inputs(tmp_path, texts):
    result, paths = [], {}
    for index, text in enumerate(texts):
        raw = text.encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = tmp_path / str(index)
        path.write_bytes(raw)
        paths[digest] = path
        source = SourceSpan(SourceArtifact(digest, len(raw)), "us_code", "fixture-release",
                            f"fixture-{index}", "en", f"1 USC {index + 1}", 0, len(raw))
        result.append(codec.EmbeddingInput(source, "1", str(index + 1), text, source.citation))
    return result, lambda ref: paths[ref["sha256"]]


def _results(inputs, model, batch_size=2):
    return runtime._produce_results(inputs, model, torch, batch_size=batch_size,
                                    token_input_digest=codec.token_input_digest)


def test_guard_restores_environment_sockets_and_bytecode_after_failure(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "original")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    originals = (socket.create_connection, socket.socket.connect, sys.dont_write_bytecode)
    with pytest.raises(RuntimeError, match="fixture stop"):
        with runtime._offline_guard():
            assert os.environ["HF_HUB_OFFLINE"] == "1"
            assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
            assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
            assert sys.dont_write_bytecode is True
            with pytest.raises(runtime.EmbeddingRuntimeError, match="network"):
                socket.create_connection(("127.0.0.1", 9))
            with socket.socket() as sock:
                with pytest.raises(runtime.EmbeddingRuntimeError, match="network"):
                    sock.connect(("127.0.0.1", 9))
            raise RuntimeError("fixture stop")
    assert os.environ["HF_HUB_OFFLINE"] == "original"
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    assert (socket.create_connection, socket.socket.connect, sys.dont_write_bytecode) == originals


def test_exact_token_boundary_and_batch_forward_keep_input_order(tmp_path):
    inputs, _ = _inputs(tmp_path, ["law " * 510, "law " * 511, "Short rule.", "Last rule here."])
    model = FixtureModel()
    results = _results(inputs, model)
    assert [row["input_id"] for row in results] == [item.input_id for item in inputs]
    assert [row["status"] for row in results] == ["embedded", "token_limit_exceeded", "embedded", "embedded"]
    assert [tuple(batch.shape) for batch in model.calls] == [(2, 512), (1, 5)]
    assert len(results[0]["tokens"]["input_ids"]) == 512
    assert results[1]["tokens"]["token_count"] == 513
    assert results[1]["vector"] is None
    assert len(results[2]["tokens"]["input_ids"]) == 4
    assert results[2]["tokens"]["attention_mask"] == [1, 1, 1, 1]


def test_oversized_whole_text_never_enters_forward(tmp_path):
    inputs, _ = _inputs(tmp_path, ["law " * 600])
    model = FixtureModel()
    result = _results(inputs, model)[0]
    assert model.calls == []
    assert result["status"] == "token_limit_exceeded"
    assert result["tokens"] == codec.token_input_digest(model.tokenizer(
        inputs[0].text, truncation=False, add_special_tokens=True, padding=False))


def test_hidden_tokenization_change_fails_before_forward(tmp_path):
    inputs, _ = _inputs(tmp_path, ["Exact untouched words."])
    model = FixtureModel(drift=True)
    with pytest.raises(runtime.EmbeddingRuntimeError, match="differ from untruncated"):
        _results(inputs, model)
    assert model.calls == []


@pytest.mark.parametrize("options", [{"dtype": torch.float64}, {"nonfinite": True}])
def test_wrong_precision_or_nonfinite_output_is_rejected(tmp_path, options):
    inputs, _ = _inputs(tmp_path, ["Exact words."])
    with pytest.raises(runtime.EmbeddingRuntimeError, match="finite CPU float32"):
        _results(inputs, FixtureModel(**options))


def test_lower_existing_context_ceiling_is_rejected_without_raising_it():
    model = SimpleNamespace(max_seq_length=256)
    with pytest.raises(runtime.EmbeddingRuntimeError, match="already be exactly 512"):
        runtime._validate_model(model, torch)
    assert model.max_seq_length == 256


def test_lower_tokenizer_ceiling_is_rejected_without_raising_it():
    model = SimpleNamespace(max_seq_length=512, tokenizer=SimpleNamespace(model_max_length=256))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="must not be below 512"):
        runtime._validate_model(model, torch)
    assert model.tokenizer.model_max_length == 256


def _snapshot(tmp_path, monkeypatch):
    snapshot = tmp_path / "models--thenlper--gte-small" / "snapshots" / runtime.PINNED_REVISION
    manifest = {}
    for name in runtime._PINNED_ASSETS:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("diagnostic fixture " + name).encode()
        path.write_bytes(raw)
        manifest[name] = (len(raw), hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(runtime, "_PINNED_ASSETS", manifest)
    return snapshot


def test_asset_manifest_detects_changed_bytes_and_unknown_configs(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path, monkeypatch)
    _, manifest = runtime._snapshot_assets(snapshot)
    assert len(manifest) == 9
    assert [row["name"] for row in manifest] == sorted(runtime._PINNED_ASSETS)
    weight = snapshot / "model.safetensors"
    original = weight.read_bytes()
    weight.write_bytes(b"x" * len(original))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="SHA-256"):
        runtime._snapshot_assets(snapshot)
    weight.write_bytes(original)
    (snapshot / "config_sentence_transformers.json").write_text("{}")
    with pytest.raises(runtime.EmbeddingRuntimeError, match="unexpected"):
        runtime._snapshot_assets(snapshot)


def test_assets_allow_cache_blob_links_but_reject_external_targets(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path, monkeypatch)
    weight = snapshot / "model.safetensors"
    raw = weight.read_bytes()
    blob = snapshot.parent.parent / "blobs" / "fixture"
    blob.parent.mkdir()
    blob.write_bytes(raw)
    try:
        weight.unlink()
        weight.symlink_to(blob)
        runtime._snapshot_assets(snapshot)
        external = tmp_path / "untrusted"
        external.write_bytes(raw)
        weight.unlink()
        weight.symlink_to(external)
        with pytest.raises(runtime.EmbeddingRuntimeError, match="inside the pinned model cache"):
            runtime._snapshot_assets(snapshot)
    finally:
        # Both real link checks execute; leave the test-owned fixture ordinary
        # for enclosing strict inventory even when a subject assertion fails.
        weight.unlink(missing_ok=True)
        weight.write_bytes(raw)


def test_source_verification_precedes_any_model_loading(tmp_path, monkeypatch):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    resolver({"sha256": inputs[0].source.artifact.sha256}).write_text("Changed bytes.")
    monkeypatch.setattr(runtime, "_snapshot_assets", lambda *args: pytest.fail("model assets accessed before source verification"))
    with pytest.raises(codec.EmbeddingProductionError, match="source bytes"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver)


def test_fixture_tensor_receipt_cannot_be_converted_to_native_corpus(tmp_path):
    inputs, resolver = _inputs(tmp_path, ["An exact diagnostic source."])
    rows = _results(inputs, FixtureModel())
    receipt = codec.build_embedding_production_receipt(
        inputs, results=rows, execution={**codec.native_execution_profile(), "kind": "injected_fixture"},
        model_assets=[{"name": name, "bytes": size, "sha256": digest}
                      for name, (size, digest) in sorted(runtime._PINNED_ASSETS.items())],
        producer={"code_sha256": "a" * 64, "runtime_versions": {
            "python": "fixture", "torch": "fixture", "transformers": "fixture", "tokenizers": "fixture",
            "sentence_transformers": "fixture"}},
        resolver=resolver)
    assert receipt.status_counts["embedded"] == 1
    assert receipt.native_execution_profile is False
    with pytest.raises(codec.EmbeddingProductionError, match="injected fixtures"):
        receipt.to_corpus_records(resolver=resolver)


def test_native_api_has_no_model_factory_escape_hatch(tmp_path):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    with pytest.raises(TypeError, match="model_factory"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver, model_factory=FixtureModel)


def test_resident_producer_source_drift_blocks_before_loading(tmp_path, monkeypatch):
    inputs, resolver = _inputs(tmp_path, ["Exact source words."])
    monkeypatch.setattr(runtime, "_LOADED_PRODUCER_SHA256", "0" * 64)
    monkeypatch.setattr(runtime, "_snapshot_assets", lambda *args: pytest.fail("model loaded after producer source drift"))
    with pytest.raises(runtime.EmbeddingRuntimeError, match="source changed"):
        runtime.produce_native_embedding_receipt(inputs, resolver=resolver)


@pytest.mark.parametrize("batch_size", [True, 0, 17])
def test_native_batch_bound_is_checked_before_loading(batch_size):
    with pytest.raises(runtime.EmbeddingRuntimeError, match="batch_size"):
        runtime.produce_native_embedding_receipt([], resolver=lambda _: None, batch_size=batch_size)


@pytest.mark.skipif(not (Path.home()/".cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd/model.safetensors").is_file(),reason="pinned local GTE-small unavailable; no download")
def test_native384_complete_formal_IR_chunks_cover_every_byte_and_actual_forward(tmp_path):
    import json
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as reviewed
    _,_,populations,_,_=reviewed._rich_v3_heldout_case()
    rows=populations["train"]+populations["holdout"]
    inputs=[];paths={}
    for index,row in enumerate(rows):
        text=json.dumps(row["canonical_ir"],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        raw=text.encode();digest=hashlib.sha256(raw).hexdigest();path=tmp_path/('formal-'+str(index)+'.json');path.write_bytes(raw);paths[digest]=path
        source=SourceSpan(SourceArtifact(digest,len(raw)),"diagnostic","fictional-reviewed-complete-IR",row["unit_id"],"en","fictional IR:"+row["id"],0,len(raw))
        inputs.append(codec.EmbeddingInput(source,"fictional complete typed IR",row["id"],text,source.citation))
    resolver=lambda ref:paths[ref["sha256"]]
    expected=hashlib.sha256(codec._canonical([item.to_dict() for item in inputs])).hexdigest()
    raw_receipt=runtime.produce_native_embedding_receipt(inputs,resolver=resolver,batch_size=1)
    assert raw_receipt.status_counts["token_limit_exceeded"]==6 and raw_receipt.status_counts["embedded"]==0
    plan=codec.prepare_native384_complete_chunks(inputs,expected_inputs_sha256=expected)
    children=[codec.EmbeddingInput.from_dict(row["input"]) for row in plan["chunks"]]
    receipt=runtime.produce_native_embedding_receipt(children,resolver=resolver,batch_size=1)
    assert receipt.status_counts["embedded"]==len(children) and all(len(row["tokens"]["input_ids"])<=512 for row in receipt.to_dict()["results"])
    bound=codec.bind_native384_complete_chunk_receipt(plan,receipt,inputs=inputs,expected_inputs_sha256=expected,expected_manifest_sha256=hashlib.sha256(codec._canonical(plan)).hexdigest(),expected_receipt_sha256=receipt.sha256)
    assert bound["complete_parent_count"]==6 and bound["aggregation_performed"] is False
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_embeddings as composition_owner
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    options=dict(inputs=inputs,expected_inputs_sha256=expected,expected_manifest_sha256=hashlib.sha256(codec._canonical(plan)).hexdigest(),expected_receipt_sha256=receipt.sha256)
    composition=composition_owner.compose_native384_complete_chunks(plan,receipt,**options)
    assert composition['available_count']==6 and composition['unavailable_count']==0
    requests=[dict(id=row['id'],input_id=item.input_id,input=dict(source_text=item.text,context=dict(role='none_required',text='',bindings={},sha256=hashlib.sha256(b'').hexdigest()))) for row,item in zip(rows,inputs,strict=True)]
    wire=composition_owner._raw(composition)
    artifact=dict(path=str(tmp_path/'actual-complete-formal-composition.json'),bytes=len(wire),sha256=hashlib.sha256(wire).hexdigest())
    lane=lanes.prepare_native384_composed_lane_bundle(composition,expected_composition_sha256=artifact['sha256'],artifact_binding=artifact,requests=requests,expected_requests_sha256=lanes._digest(requests))
    checked=lanes.validate_lane_bundle(lane['bundle'],expected_bindings=lane['expected_bindings'])
    assert checked['stage']=='complete_chunk_composition' and checked['available_count']==6
    assert all(len(row['vector'])==384 and row['upstream_vector_sha256'] is not None for row in lane['bundle']['rows'])
    (tmp_path/'actual-complete-formal-composition.json').write_bytes(wire)
    (tmp_path/'actual-complete-formal-composed-lane.json').write_bytes(lanes._raw(lane))
    for original in inputs:
        chunks=[codec.EmbeddingInput.from_dict(row["input"]) for row in plan["chunks"] if row["parent_input_id"]==original.input_id]
        assert b''.join(item.text.encode() for item in chunks)==original.text.encode()
    receipt.save(tmp_path/'actual-complete-formal-chunk-receipt.json',resolver=resolver)
    raw_receipt.save(tmp_path/'actual-complete-formal-raw-refusal.json',resolver=resolver)
    (tmp_path/'actual-complete-formal-chunk-manifest.json').write_bytes(codec._canonical(plan))
    (tmp_path/'actual-complete-formal-chunk-binding.json').write_bytes(codec._canonical(bound))



def _run_actual_complete_GTE_reviewed_case(tmp_path, *, reviewed_case=None):
    """Real cached encoder/projection execution on fictional reviewed TRAIN data."""
    import json
    from copy import deepcopy
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_declarations as declarations
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as reviewed
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_embeddings as numerical
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_relation_mask_handoff as masks
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as snapshot_owner

    case=declarations.reviewed_pair_fixture_v3() if reviewed_case is None else reviewed_case
    preparation_inputs=case['preparation_inputs'];body=preparation_inputs['body']
    before_endpoints=deepcopy({side:body[side+'_endpoints'] for side in ('source','formal')})
    before_pairs=deepcopy(body['pairs'])
    products={}
    def save(name,value):
        raw=codec._canonical(value);path=tmp_path/name;path.write_bytes(raw)
        return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    for side in ('source','formal'):
        previous=preparation_inputs[side+'_lane'];original_inputs=[];paths={};requests=[]
        for ordinal,row in enumerate(previous['rows']):
            text=row['input']['source_text']
            # Formal aliases retain separate physical diagnostic occurrences;
            # exact encoder text and every typed field remain unchanged.
            prefix=(side+':'+str(ordinal)+'\n').encode();payload=text.encode();raw=prefix+payload
            path=tmp_path/(side+'-'+str(ordinal)+'.txt');path.write_bytes(raw)
            artifact=SourceArtifact(hashlib.sha256(raw).hexdigest(),len(raw));paths[artifact.sha256]=path
            span=SourceSpan(artifact,'diagnostic','fictional-reviewed-v3-GTE',row['id'],'en',
                'fictional diagnostic '+row['id'],len(prefix),len(raw))
            item=codec.EmbeddingInput(span,'fictional reviewed complete input',row['id'],text,span.citation)
            original_inputs.append(item)
            requests.append(dict(id=row['id'],input_id=item.input_id,input=deepcopy(row['input'])))
        resolver=lambda ref:paths[ref['sha256']]
        original_sha=hashlib.sha256(codec._canonical([item.to_dict() for item in original_inputs])).hexdigest()
        plan=codec.prepare_native384_complete_chunks(original_inputs,expected_inputs_sha256=original_sha)
        if side=='formal':
            raw_refusal=runtime.produce_native_embedding_receipt(original_inputs,resolver=resolver,batch_size=1)
            assert raw_refusal.status_counts['token_limit_exceeded']==len(original_inputs)
            raw_refusal.save(tmp_path/'actual-joint-formal-raw-refusal.json',resolver=resolver)
        children=[codec.EmbeddingInput.from_dict(chunk['input']) for chunk in plan['chunks']]
        native=runtime.produce_native_embedding_receipt(children,resolver=resolver,batch_size=1)
        assert native.native_execution_profile and native.status_counts['embedded']==len(children)
        assert all(len(row['tokens']['input_ids'])<=512 for row in native.to_dict()['results'])
        options=dict(inputs=original_inputs,expected_inputs_sha256=original_sha,
            expected_manifest_sha256=hashlib.sha256(codec._canonical(plan)).hexdigest(),expected_receipt_sha256=native.sha256)
        composed=numerical.compose_native384_complete_chunks(plan,native,**options)
        assert composed['available_count']==len(original_inputs) and composed['unavailable_count']==0
        descriptor=save('actual-joint-'+side+'-composition.json',composed)
        converted=lanes.prepare_native384_composed_lane_bundle(composed,
            expected_composition_sha256=descriptor['sha256'],artifact_binding=descriptor,
            requests=requests,expected_requests_sha256=lanes._digest(requests))
        bundle=converted['bundle']
        assert [row['input'] for row in bundle['rows']]==[row['input'] for row in previous['rows']]
        for endpoint,row in zip(body[side+'_endpoints'],bundle['rows'],strict=True):
            assert endpoint['id']==row['id'] and endpoint['input_sha256']==row['input_sha256']
            endpoint['vector_sha256']=row['vector_sha256']
        preparation_inputs[side+'_lane']=bundle
        preparation_inputs['expected_'+side+'_lane_bindings']=converted['expected_bindings']
        body[side+'_lane_sha256']=lanes._digest(bundle)
        dependency=body['ledger_id']+':'+side+'-lane'
        next(row for row in preparation_inputs['dependency_manifest']['artifacts'] if row['artifact_id']==dependency)['artifact_sha256']=lanes._digest(bundle)
        case['observed_artifacts'][dependency]=lanes._digest(bundle)
        native.save(tmp_path/('actual-joint-'+side+'-native-receipt.json'),resolver=resolver)
        products[side]=dict(original_inputs=len(original_inputs),chunk_rows=len(children),
            max_forward_tokens=max(len(row['tokens']['input_ids']) for row in native.to_dict()['results']),
            native_receipt_sha256=native.sha256,composition=descriptor,
            manifest=save('actual-joint-'+side+'-manifest.json',plan),
            lane=save('actual-joint-'+side+'-lane.json',converted))
    assert preparation_inputs['source_lane']['profile']==preparation_inputs['formal_lane']['profile']
    assert body['pairs']==before_pairs
    for side in ('source','formal'):
        for old,new in zip(before_endpoints[side],body[side+'_endpoints'],strict=True):
            assert {key:value for key,value in old.items() if key!='vector_sha256'}=={key:value for key,value in new.items() if key!='vector_sha256'}
    preparation_inputs['representation_stage']='complete_chunk_composition'
    reviewed.refresh_reviewed_pair_ledger_v3(case)
    args,options=reviewed.reviewed_mask_arguments_v2(case)
    handoff=masks.compile_reviewed_train_relation_masks_v3(*args,**options)
    assert handoff['reviewed_objective_mask_ready'] is True and handoff['fixture_only'] is True
    assert handoff['production_contrastive_mask']==handoff['training_gold_mask']==handoff['evaluation_gold_mask']==0
    for index,pair in enumerate(body['pairs']):
        i,j=divmod(index,handoff['formal_row_count'])
        if pair['relation'] in ('unknown','analogy'):
            assert handoff['objective_positive_mask'][i][j] is handoff['objective_permitted_negative_mask'][i][j] is False
    fitted=joint.train_reviewed_retriever_v3(*args,**options,steps=1,joint_dimension=8)
    assert fitted['report']['optimizer_steps']==1 and fitted['report']['changed_parameter_names']
    assert fitted['checkpoint']['training_handoff']==handoff
    checkpoint_path=tmp_path/'actual-GTE-reviewed-joint-checkpoint.json'
    checkpoint_sha=joint.save_checkpoint(fitted['checkpoint'],checkpoint_path)
    assert joint.load_checkpoint(checkpoint_path,checkpoint_sha)==fitted['checkpoint']
    report=save('actual-GTE-reviewed-joint-training-report.json',fitted['report'])
    handoff_ref=save('actual-GTE-reviewed-joint-handoff.json',handoff)
    pair_ref=save('actual-GTE-reviewed-joint-pair-preparation.json',case['preparation'])
    # Capture the complete original review replay inputs, including each byte
    # leaf, as diagnostic DATA. This is never imported as a trusted admission.
    snapshot,commitment=snapshot_owner._snapshot(dict(args=list(args),kwargs=options))
    byte_leaves=[]
    def capture(value,path):
        if type(value) is bytes:
            leaf=tmp_path/('review-byte-'+hashlib.sha256(value).hexdigest()+'.bin')
            if not leaf.exists():leaf.write_bytes(value)
            byte_leaves.append(dict(path=path,artifact=dict(path=str(leaf),bytes=len(value),sha256=hashlib.sha256(value).hexdigest())))
            return None
        if type(value) is dict:return {key:capture(item,path+[key]) for key,item in value.items()}
        if type(value) is list:return [capture(item,path+[index]) for index,item in enumerate(value)]
        return value
    captured=save('actual-GTE-reviewed-joint-original-review-inputs.json',dict(
        schema='diagnostic-review-input-byte-capture/v1',snapshot_commitment=commitment,
        skeleton=capture(snapshot,[]),byte_leaves=byte_leaves,admission_authority=False))
    save('actual-GTE-reviewed-joint-run.json',dict(schema='actual-GTE-reviewed-joint-operation/v1',
        products=products,source_rows=handoff['source_row_count'],formal_rows=handoff['formal_row_count'],
        positive_pairs=handoff['objective_positive_pair_count'],permitted_negative_pairs=handoff['objective_permitted_negative_pair_count'],
        unknown_pairs=handoff['unknown_pair_count'],analogy_pairs=handoff['analogy_retrieval_only_pair_count'],
        optimizer_steps=1,checkpoint=dict(path=str(checkpoint_path),sha256=checkpoint_sha),
        training_report=report,handoff=handoff_ref,pair_preparation=pair_ref,original_review_inputs=captured,
        actual_encoder_executed=True,actual_masked_projection_update_executed=True,
        fictional_reviewed_TRAIN_only=True,heldout_quality_evaluated=False,statutory_meaning_admitted=False,
        source_formal_profile=preparation_inputs['source_lane']['profile']))

    return case,fitted,save


@pytest.mark.skipif(not (Path.home()/".cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd/model.safetensors").is_file(), reason="pinned local GTE-small unavailable; no download")
def test_actual_complete_GTE_source_formal_vectors_reach_reviewed_v3_masked_joint_fit(tmp_path):
    _run_actual_complete_GTE_reviewed_case(tmp_path)


@pytest.mark.skipif(not (Path.home()/".cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd/model.safetensors").is_file(), reason="pinned local GTE-small unavailable; no download")
def _run_actual_GTE_fixed_heldout_case(tmp_path):
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluated
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_declarations as declarations
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as reviews
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_embeddings as numerical
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm
    helper,options,populations,replays,components=evaluated._rich_v3_heldout_case()
    context=options['reviewed_training_context']
    case=declarations.reviewed_pair_fixture_v3(include_definition=True,
        reviewed_norm_case=components['train'],shared_split_manifest=context['split_manifest'],
        sample_ids_by_unit={row['unit_id']:row['id'] for row in populations['train']})
    case,fitted,save=_run_actual_complete_GTE_reviewed_case(tmp_path,reviewed_case=case)
    checkpoint=fitted['checkpoint'];checkpoint_sha=joint.checkpoint_digest(checkpoint)
    model=joint.ReviewedLegalJointRetriever(checkpoint,expected_checkpoint_sha256=checkpoint_sha)
    queries=[dict(id=row['id'],source_text=row['source_text'],split_sample_id=row['id']) for row in populations['holdout']]
    heldout=options['binding'].receipt()['heldout_evaluation']
    disjoint=structured._require_disjoint_heldout_review(heldout,replays['train'],populations['train'],queries,
        splits.LegalIRSplitManifest.from_mapping(context['split_manifest']),_admission_version='v3')
    inputs=[];paths={};requests=[]
    for ordinal,row in enumerate(queries):
        raw=row['source_text'].encode();path=tmp_path/('heldout-source-'+str(ordinal)+'.txt');path.write_bytes(raw)
        artifact=SourceArtifact(hashlib.sha256(raw).hexdigest(),len(raw));paths[artifact.sha256]=path
        span=SourceSpan(artifact,'diagnostic','fictional-disjoint-heldout',row['id'],'en','fictional heldout '+row['id'],0,len(raw))
        item=codec.EmbeddingInput(span,'heldout source only',row['id'],row['source_text'],span.citation);inputs.append(item)
        requests.append(dict(id=row['id'],input_id=item.input_id,input=dict(source_text=row['source_text'],
            context=dict(role='none_required',text='',bindings={},sha256=hashlib.sha256(b'').hexdigest()))))
    resolver=lambda ref:paths[ref['sha256']]
    source_sha=hashlib.sha256(codec._canonical([item.to_dict() for item in inputs])).hexdigest()
    manifest=codec.prepare_native384_complete_chunks(inputs,expected_inputs_sha256=source_sha)
    native=runtime.produce_native_embedding_receipt([codec.EmbeddingInput.from_dict(row['input']) for row in manifest['chunks']],resolver=resolver,batch_size=1)
    assert native.status_counts['embedded']==len(manifest['chunks'])
    composed=numerical.compose_native384_complete_chunks(manifest,native,inputs=inputs,expected_inputs_sha256=source_sha,
        expected_manifest_sha256=hashlib.sha256(codec._canonical(manifest)).hexdigest(),expected_receipt_sha256=native.sha256)
    wire=lanes._raw(composed);file=tmp_path/'heldout-source-composition.json';file.write_bytes(wire)
    descriptor=dict(path=str(file),bytes=len(wire),sha256=hashlib.sha256(wire).hexdigest())
    query_lane=lanes.prepare_native384_composed_lane_bundle(composed,expected_composition_sha256=descriptor['sha256'],
        artifact_binding=descriptor,requests=requests,expected_requests_sha256=lanes._digest(requests))
    assert query_lane['bundle']['profile']==case['preparation_inputs']['source_lane']['profile']
    # Only opaque exclusion hashes enter ranking. Full reviewed reference IR is
    # retained separately after the frozen producer call, for later evaluation.
    excluded={row['id']:[lanes._digest(row['canonical_ir'])] for row in populations['holdout']}
    args,kwargs=reviews.reviewed_mask_arguments_v2(case)
    common=dict(query_source_lane=query_lane['bundle'],expected_query_lane_bindings=query_lane['expected_bindings'],
        expected_query_split='holdout',forbidden_reference_formal_sha256s=excluded,
        expected_forbidden_reference_sha256=lanes._digest(excluded),top_k=4)
    frozen_input_sha=lanes._digest(dict(queries=queries,common=common))
    outcomes={}
    for mode in ('lexical','raw','joint'):
        output=model.retrieve(queries,*args,**kwargs,**common,mode=mode)
        assert output['status']=='retrieval_completed' and output['retrieved_count']==3 and output['abstention_count']==0
        assert output['model_forward_executed'] is (mode=='joint')
        assert output['query_target_access'] is output['legal_applicability_verified'] is output['decoder_context_admitted'] is False
        assert all(len(row['retrieved_ids'])==row['eligible_rows']==4 for row in output['rows'])
        outcomes[mode]=output
    assert lanes._digest(dict(queries=queries,common=common))==frozen_input_sha
    assert model.checkpoint==checkpoint
    native.save(tmp_path/'actual-heldout-source-native-receipt.json',resolver=resolver)
    save('actual-heldout-source-chunk-manifest.json',manifest)
    save('actual-heldout-query-lane.json',query_lane)
    save('actual-heldout-reference-population.json',populations['holdout'])
    save('actual-heldout-source-dependency-receipt.json',heldout)
    # These are rankings of structural examples. No cross-component semantic
    # relevance or legal applicability judgments are invented or scored.
    save('actual-GTE-fixed-heldout-comparison.json',dict(schema='actual-GTE-fixed-heldout-ranking-comparison/v1',
        modes=outcomes,query_input_sha256=frozen_input_sha,queries=queries,checkpoint_sha256=checkpoint_sha,
        query_encoder_receipt_sha256=native.sha256,training_dependency_manifest_sha256=disjoint,
        source_and_legal_dependency_groups_disjoint=True,common_candidate_count=4,common_top_k=4,
        independent_reference_targets_forwarded=False,semantic_relevance_judgments='unprovided',
        semantic_correspondence_metrics=None,legal_applicability_metrics=None,statutory_admission=False))

    return dict(case=case, model=model, queries=queries, args=args, kwargs=kwargs, common=common,
        options=options, populations=populations, replays=replays, components=components,
        outcomes=outcomes, checkpoint_sha=checkpoint_sha, save=save)


def test_actual_GTE_fixed_heldout_queries_compare_lexical_raw_and_joint_without_reference_payload(tmp_path):
    _run_actual_GTE_fixed_heldout_case(tmp_path)

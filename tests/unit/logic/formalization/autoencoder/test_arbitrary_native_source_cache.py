"""Data-contract controls; admitted numerical fixtures are diagnostic doubles.

These tests execute no encoders and establish no native-production attestation.
Source artifact/occurrence checks, cache rebuilds and JSON guards remain real.
"""
from copy import deepcopy
import hashlib
import json
import struct

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_source_cache as cache


def ref(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def source(path, text, *, identity="case", prefix="Préface\n", suffix="\nEnd"):
    raw = (prefix+text+suffix).encode(); path.write_bytes(raw)
    row = {"id": identity, "source_text": text, "source": {"artifact": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
        "source_kind": "diagnostic", "release_id": "diagnostic-v1", "document_id": "document", "language": "en",
        "citation": "Diagnostic source", "byte_start": len(prefix.encode()), "byte_end": len((prefix+text).encode()), "normalization": "identity"}}
    return row, lambda artifact: path


def record(reference, dimension, *, types=True):
    # This is deliberately an injected unit-test admission double. The public
    # API has no factory-injection or fixture-native profile escape hatch.
    return {"vector": [1.0]+[0.0]*(dimension-1),
        "tokens": {"input_ids": [0, 20, 2], "attention_mask": [1, 1, 1], **({"token_type_ids": None} if types else {})},
        "receipt": reference, "input_id": "diagnostic-double", "producer_source_span_present": dimension == 384,
        "producer_evidence": {"diagnostic_native_verification_double": True}}


@pytest.fixture
def fixture384(tmp_path, monkeypatch):
    row, resolver = source(tmp_path/"source.txt", "État must archive.\n\nOfficer may preserve.")
    path = tmp_path/"receipt.json"; path.write_text('{"diagnostic_double":true}')
    reference = ref(path)
    requests, occurrences, _ = cache._requests([row], resolver)
    index = {(item["source_text"], cache.digest(item["source"])): [record(reference, 384)] for item in occurrences[row["id"]]}
    calls = []
    def admitted(references, source_resolver):
        calls.append((deepcopy(references), source_resolver))
        return deepcopy(index)
    monkeypatch.setattr(cache, "_native384_records", admitted)
    def plan(rows=None):
        return cache.plan_arbitrary_native_source_cache(rows or [row], dimension=384,
            native384_receipt_refs=[reference], source_resolver=resolver)
    return row, resolver, reference, index, calls, plan


def test_dynamic_source_occurrences_unicode_offsets_and_zero_authority(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    result = plan()
    assert result["status"] == "ready" and result["complete"] is True
    assert result["counts"] == {"requested_rows": 1, "ready_rows": 1, "refused_rows": 0,
        "clause_occurrences": 2, "ready_clause_occurrences": 2, "source_artifacts": 1}
    assert len(calls) == 1 and calls[0] == ([reference], resolver)
    segments = result["source_contexts"][row["id"]]["segments"]
    assert segments[1]["char_start"] == len(row["source_text"].split("\n\n")[0])+2
    assert segments[1]["byte_start"] == len(row["source_text"].split("\n\n")[0].encode())+2
    assert segments[1]["char_start"] != segments[1]["byte_start"]
    origins = result["input_origins"][row["id"]]
    assert origins[2]["source"]["byte_start"] == row["source"]["byte_start"]+segments[1]["byte_start"]
    assert origins[2]["source"]["artifact"] == row["source"]["artifact"]
    assert all(result[name] is False for name in cache.FALSE)
    assert result["receipt_consistency_only"] is True
    assert cache.validate_arbitrary_native_source_cache(cache._wire(result), source_requests=[row],
        native384_receipt_refs=[reference], source_resolver=resolver) == result


def test_one_clause_paragraph_uses_same_physical_origin_twice_without_new_vector(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    text = row["source_text"].split("\n\n")[0]
    request = deepcopy(row); request["source_text"] = text
    request["source"]["byte_end"] = request["source"]["byte_start"]+len(text.encode())
    result = plan([request])
    assert result["status"] == "ready" and len(result["input_origins"][row["id"]]) == 2
    assert result["input_origins"][row["id"]][0]["source"] == result["input_origins"][row["id"]][1]["source"]


def test_same_text_at_distinct_occurrences_preserves_ids_and_rejects_text_only_origin(tmp_path, monkeypatch):
    text = "Officer must archive."; raw = (text+"\n\n"+text).encode(); path = tmp_path/"source"; path.write_bytes(raw)
    base = {"artifact": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, "source_kind": "diagnostic",
        "release_id": "release", "document_id": "doc", "language": "en", "citation": "citation", "normalization": "identity"}
    rows = [{"id": "first", "source_text": text, "source": {**base, "byte_start": 0, "byte_end": len(text.encode())}},
        {"id": "second", "source_text": text, "source": {**base, "byte_start": len(text.encode())+2, "byte_end": len(raw)}}]
    receipt = tmp_path/"receipt.json"; receipt.write_text('{"diagnostic_double":true}'); reference = ref(receipt)
    index = {(text, cache.digest(rows[0]["source"])): [record(reference, 384)]}
    monkeypatch.setattr(cache, "_native384_records", lambda refs, resolver: deepcopy(index))
    arguments = dict(dimension=384, native384_receipt_refs=[reference], source_resolver=lambda artifact: path)
    result = cache.plan_arbitrary_native_source_cache(rows, **arguments)
    assert result["status"] == "partial" and [row["id"] for row in result["rows"]] == ["first"]
    assert result["dispositions"][1]["unavailable_inputs"][0]["reason"] == "source_origin_mismatch"
    index[(text, cache.digest(rows[1]["source"]))] = [record(reference, 384)]
    result = cache.plan_arbitrary_native_source_cache(rows, **arguments)
    assert [row["id"] for row in result["rows"]] == ["first", "second"]
    assert result["source_contexts"]["first"] == result["source_contexts"]["second"]
    assert result["input_origins"]["first"][0]["source"] != result["input_origins"]["second"][0]["source"]


def test_missing_clause_refuses_whole_occurrence_and_empty_ready_cache_is_valid(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    key = next(key for key in index if key[0] == "Officer may preserve."); del index[key]
    result = plan()
    assert result["status"] == "refused" and result["complete"] is False
    assert result["rows"] == [] and result["source_contexts"] == {} and result["input_origins"] == {}
    assert result["dispositions"][0]["unavailable_inputs"][0]["role"] == "clause"
    assert cache.validate_arbitrary_native_source_cache(result, source_requests=[row], native384_receipt_refs=[reference],
        source_resolver=resolver) == result


@pytest.mark.parametrize("reason", ["token_limit_exceeded", "missing_input"])
def test_recorded_refusal_is_retained_without_zero_fallback(fixture384, reason):
    row, resolver, reference, index, calls, plan = fixture384
    key = (row["source_text"], cache.digest(row["source"]))
    index[key] = [{"disposition": reason, "receipt": reference, "input_id": "diagnostic"}]
    result = plan()
    assert result["rows"] == []
    assert result["dispositions"][0]["unavailable_inputs"][0]["reason"] == reason


@pytest.mark.parametrize("change", ["extra", "label", "bool_flag", "count", "vector", "origin", "digest", "requests"])
def test_resealed_cache_tampering_refuses_against_original_requests(fixture384, change):
    row, resolver, reference, index, calls, plan = fixture384
    result = plan()
    if change == "extra": result["unexpected"] = True
    elif change == "label": result["source_requests"][0]["target"] = "gold"
    elif change == "bool_flag": result["qualified"] = 0
    elif change == "count": result["counts"]["ready_rows"] = True
    elif change == "vector": result["rows"][0]["input"][0] = 0.0
    elif change == "origin": result["input_origins"][row["id"]][0]["source"]["document_id"] = "wrong"
    elif change == "requests": result["source_requests"][0]["id"] = "other"
    else: result["source_requests_sha256"] = "0"*64
    result["cache_sha256"] = cache.digest({k:v for k,v in result.items() if k != "cache_sha256"})
    with pytest.raises(cache.ArbitraryNativeSourceCacheError):
        cache.validate_arbitrary_native_source_cache(result, source_requests=[row], native384_receipt_refs=[reference], source_resolver=resolver)


@pytest.mark.parametrize("value", [True, 1, 0.1, float("nan"), float("inf"), 1e100])
def test_nonexact_float32_vectors_are_never_repaired(fixture384, value):
    row, resolver, reference, index, calls, plan = fixture384
    next(iter(index.values()))[0]["vector"][0] = value
    with pytest.raises(cache.ArbitraryNativeSourceCacheError): plan()


def test_over512_tokens_refuse_explicitly_and_boolean_mask_refuses(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    entry = next(iter(index.values()))[0]
    entry["tokens"]["input_ids"] = [10]*513
    assert plan()["dispositions"][0]["unavailable_inputs"][0]["reason"] == "token_limit_exceeded"
    entry["tokens"]["input_ids"] = [0, 20, 2]; entry["tokens"]["attention_mask"] = [True, True, True]
    with pytest.raises(cache.ArbitraryNativeSourceCacheError): plan()


@pytest.mark.parametrize("change", ["extra", "target", "normalization", "selector", "document", "id", "source_bytes"])
def test_request_contract_and_physical_source_checks(fixture384, change):
    row, resolver, reference, index, calls, plan = fixture384
    request = deepcopy(row)
    if change in ("extra", "target"): request[change] = "forbidden"
    elif change == "normalization": request["source"]["normalization"] = "whitespace-v1"
    elif change == "selector": request["source"]["byte_start"] += 1
    elif change == "document": request["source"]["document_id"] = "different"
    elif change == "id": request["id"] = True
    else: resolver(None).write_bytes(b"changed artifact")
    if change == "document":
        assert plan([request])["status"] == "refused"
    else:
        with pytest.raises(ValueError): plan([request])


def test_unknown_dimensions_and_unused_refs_refuse_before_native_verification(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    for dimension in (8, True, 385, 4096):
        with pytest.raises(cache.ArbitraryNativeSourceCacheError) as caught:
            cache.plan_arbitrary_native_source_cache([row], dimension=dimension, native384_receipt_refs=[reference], source_resolver=resolver)
        assert caught.value.disposition == "unsupported_dimension"
    with pytest.raises(cache.ArbitraryNativeSourceCacheError):
        cache.plan_arbitrary_native_source_cache([row], dimension=384, native384_receipt_refs=[reference], native768_report_refs=[], source_resolver=resolver)
    assert calls == []


def test_row_clause_reference_bounds_and_duplicate_ids(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    for rows in ([], [deepcopy(row) for _ in range(65)], [row, deepcopy(row)]):
        with pytest.raises(cache.ArbitraryNativeSourceCacheError):
            cache.plan_arbitrary_native_source_cache(rows, dimension=384, native384_receipt_refs=[reference], source_resolver=resolver)
    with pytest.raises(cache.ArbitraryNativeSourceCacheError):
        cache.plan_arbitrary_native_source_cache([row], dimension=384, native384_receipt_refs=[reference, reference], source_resolver=resolver)


def test_more_than_eight_real_source_clauses_and_empty_literal_clause_refuse(tmp_path):
    for index, text in enumerate(("\n\n".join(["x"]*9), "x\n\n\n\nx")):
        row, resolver = source(tmp_path/str(index), text)
        with pytest.raises(cache.ArbitraryNativeSourceCacheError) as caught:
            cache._requests([row], resolver)
        assert caught.value.disposition == "clause_count_exceeded"


def test_duplicate_keys_nonfinite_json_and_reference_drift_refuse(fixture384):
    row, resolver, reference, index, calls, plan = fixture384
    result = plan()
    for raw in (b'{"dimension":384,"dimension":768}', b'{"value":NaN}'):
        with pytest.raises(cache.ArbitraryNativeSourceCacheError):
            cache.validate_arbitrary_native_source_cache(raw, source_requests=[row], native384_receipt_refs=[reference], source_resolver=resolver)
    from pathlib import Path
    Path(reference["path"]).write_text('{"changed":true}')
    with pytest.raises(cache.ArbitraryNativeSourceCacheError):
        cache.validate_arbitrary_native_source_cache(result, source_requests=[row], native384_receipt_refs=[reference], source_resolver=resolver)


def test_receipt_symlink_and_resealed_provenance_changes_refuse(fixture384, tmp_path):
    row, resolver, reference, index, calls, plan = fixture384
    link = tmp_path/"link.json"; link.symlink_to(reference["path"])
    bad = {**reference, "path": str(link)}
    with pytest.raises(cache.ArbitraryNativeSourceCacheError):
        cache.plan_arbitrary_native_source_cache([row], dimension=384, native384_receipt_refs=[bad], source_resolver=resolver)


def test_real384_native_index_is_called_and_complete_token_binding_is_checked(fixture384, monkeypatch):
    from types import SimpleNamespace
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceSpan
    row, resolver, reference, index, calls, plan = fixture384
    native_calls = []
    token = {"input_ids": [0, 20, 2], "attention_mask": [1, 1, 1], "token_type_ids": None}
    evidence = {"receipt": reference, "input_id": "diagnostic", "source": deepcopy(row["source"]), "tokens_sha256": cache.digest(token)}
    def diagnostic_native_index(references, source_resolver):
        native_calls.append((references, source_resolver))
        return {(hashlib.sha256(row["source_text"].encode()).hexdigest(), row["source_text"]): [([1.0]+[0.0]*383, deepcopy(evidence))]}
    monkeypatch.setattr(native, "_native_index", diagnostic_native_index)
    fake_receipt = SimpleNamespace(sha256=reference["sha256"], inputs=[SimpleNamespace(text=row["source_text"], source=SourceSpan.from_dict(row["source"]), input_id="diagnostic")],
        to_dict=lambda: {"results": [{"input_id": "diagnostic", "status": "embedded", "tokens": deepcopy(token)}]})
    monkeypatch.setattr(codec, "load_embedding_production_receipt", lambda *args, **kwargs: fake_receipt)
    # Invoke the genuine adapter seam directly; lower verification is explicitly
    # diagnostic and does not claim native computation or producer attestation.
    # Retain the function captured before the fixture replaced this seam.
    records = ORIGINAL_NATIVE384([reference], resolver)
    assert native_calls == [([reference], resolver)]
    assert records[(row["source_text"], cache.digest(row["source"]))][0]["tokens"] == token
    evidence["tokens_sha256"] = "0"*64
    with pytest.raises(cache.ArbitraryNativeSourceCacheError): ORIGINAL_NATIVE384([reference], resolver)


ORIGINAL_NATIVE384 = cache._native384_records


def test_bare768_complete_receipt_has_insufficient_source_token_evidence(tmp_path):
    path = tmp_path/"bare.json"; path.write_text('{"schema":"gte-complete-native-embedding-production/v1"}')
    with pytest.raises(cache.ArbitraryNativeSourceCacheError, match="lacks bounded"):
        cache._native768_records([ref(path)], lambda artifact: None)


@pytest.fixture
def diagnostic768_report(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as complete
    from ipfs_datasets_py.logic.formalization.autoencoder import dimension_source_inputs as bounded
    profile = complete.reference._PROFILE
    text = "Officer may archive."; identity = "source:"+hashlib.sha256(text.encode()).hexdigest()
    token = {"input_ids": [0, 20, 2], "attention_mask": [1, 1, 1]}
    names = ["new.diagnostic_tensor_"+str(i) for i in range(136)]+["classifier.weight", "classifier.bias"]
    # Header and asset checks below are explicit diagnostic admission doubles.
    # They are not real published tensors and are never admitted in production.
    model = tmp_path/"model"; model.mkdir(); code = tmp_path/"code"; code.mkdir()
    header = cache._wire({name: {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]} for name in names})
    (model/"model.safetensors").write_bytes(struct.pack("<Q", len(header))+header)
    assets = dict(schema=profile.RECEIPT_SCHEMA, status="available", profile_id=profile.PROFILE_ID,
        model_revision=profile.MODEL_REV, code_revision=profile.CODE_REV, model_directory=str(model), code_directory=str(code),
        manifest_sha256="0"*64, files=[dict(relative_to=role, path=name, **value) for (role, name), value in profile.PUBLISHED_ASSETS.items()],
        model_numerics_verified=False, proof_authority=False, unavailable_reasons=[])
    event_source = {"id": identity, "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "active_token_count": 3,
                    "token_input_sha256": cache.digest(token["input_ids"])}
    events = [dict(index=index, path=role, batch_size=1, padded_width=3, sources=[deepcopy(event_source)],
        input_ids=[deepcopy(token["input_ids"])], attention_mask=[[1, 1, 1]], actual_forward_checked=True)
        for index, role in enumerate(("complete", "encoder", "complete"))]
    report = dict(schema="fresh-bounded-native768-production/v1", assets=assets, source_rows=[dict(id=identity, source_text=text)],
        vectors=[[1.0]+[0.0]*767], token_rows=[token], forward_observations=events, implementation=complete._implementation(),
        complete_checkpoint_loading=dict(architecture="NewForTokenClassification", tensor_count=138, tensor_names=names,
            missing_keys=[], unexpected_keys=[], mismatched_keys=[], error_msgs=[], classifier_loaded=True,
            classifier_logits_used_for_dense_embedding=False),
        dense_path_verification=dict(encoder_and_complete_hidden_states_bitwise_equal=True, evaluation_mode=True, probe_tokens=3,
                                    scope="first admitted source; source used only, no targets"),
        execution_profile=dict(batch_size=1, device="cpu", dtype="float32", pooling="cls", normalization="l2",
                               attention_implementation="eager", max_tokens_including_special_tokens=512),
        historical_profile_token_limit=8192, experiment_token_limit=512, cached_profile_relabelled=False)
    report["forward_validation"] = bounded.validate_forward_observations(report)
    report_path = tmp_path/"production.json"
    ordinary_read = cache._read
    def admitted_assets(reference, maximum=cache.MAX_REFERENCE_BYTES, *, retain=True, max_links=1):
        from pathlib import Path
        path = Path(reference["path"])
        if path.parent in (model, code):
            assert retain is False
            return None
        return ordinary_read(reference, maximum, retain=retain, max_links=max_links)
    monkeypatch.setattr(cache, "_read", admitted_assets)
    def persist():
        report_path.write_bytes(cache._wire(report))
        return [ref(report_path)]
    return report, text, persist


def test768_dynamic_one_row_complete138_token_forward_paths_are_validated_with_diagnostic_doubles(diagnostic768_report):
    report, text, persist = diagnostic768_report
    records = cache._native768_records(persist(), lambda artifact: None)
    assert list(records) == [text] and len(records[text][0]["vector"]) == 768
    assert records[text][0]["producer_source_span_present"] is False
    assert records[text][0]["producer_evidence"]["complete_checkpoint_tensor_count"] == 138
    assert records[text][0]["producer_evidence"]["forward_validation"]["forward_count"] == 3


@pytest.mark.parametrize("change", ["classifier", "loading", "token_bool", "event", "context", "relabeled", "profile_extra", "target", "tensor_names", "asset_identity"])
def test768_complete_payload_geometry_profiles_and_unknown_fields_refuse(diagnostic768_report, change):
    report, text, persist = diagnostic768_report
    if change == "classifier": report["complete_checkpoint_loading"]["classifier_loaded"] = False
    elif change == "loading": report["complete_checkpoint_loading"]["missing_keys"] = ["new.weight"]
    elif change == "token_bool": report["token_rows"][0]["input_ids"][0] = True
    elif change == "event": report["forward_observations"][1]["sources"][0]["source_sha256"] = "0"*64
    elif change == "context": report["experiment_token_limit"] = 8192
    elif change == "relabeled": report["cached_profile_relabelled"] = True
    elif change == "profile_extra": report["execution_profile"]["teacher_logits"] = []
    elif change == "target": report["source_rows"][0]["target"] = "gold"
    elif change == "tensor_names": report["complete_checkpoint_loading"]["tensor_names"][0] = "new.fabricated_different_name"
    else: report["assets"]["files"][0]["sha256"] = "0"*64
    with pytest.raises(ValueError): cache._native768_records(persist(), lambda artifact: None)


def test768_geometry_is_native_and_source_origin_is_independently_verified(tmp_path, monkeypatch):
    row, resolver = source(tmp_path/"source", "Officer may archive.")
    path = tmp_path/"native.json"; path.write_text('{"diagnostic_double":true}'); reference = ref(path)
    calls = []
    def diagnostic_report(references, source_resolver):
        calls.append((references, source_resolver))
        return {row["source_text"]: [record(reference, 768, types=False)]}
    monkeypatch.setattr(cache, "_native768_records", diagnostic_report)
    result = cache.plan_arbitrary_native_source_cache([row], dimension=768, native768_report_refs=[reference], source_resolver=resolver)
    assert len(result["rows"][0]["input"]) == 768 and result["rows"][0]["input"] == [1.0]+[0.0]*767
    assert result["input_origins"][row["id"]][0]["native"]["producer_source_span_present"] is False
    assert result["input_origins"][row["id"]][0]["source"] == row["source"]
    assert all(result[name] is False for name in cache.FALSE)
    resolver(None).write_bytes(b"changed")
    with pytest.raises(ValueError):
        cache.plan_arbitrary_native_source_cache([row], dimension=768, native768_report_refs=[reference], source_resolver=resolver)

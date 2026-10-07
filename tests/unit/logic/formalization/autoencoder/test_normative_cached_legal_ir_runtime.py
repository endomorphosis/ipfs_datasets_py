"""Retained-cache boundaries using synthetic receipts and inert decoder calls.

No test vector or producer double is evidence of an encoder execution. Only the
native binding verifier is replaced for these synthetic metadata fixtures;
source shape, receipt seals, assembly, joins, custody and checkpoint gates run.
"""
from copy import deepcopy
import importlib
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as original
from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs as fresh
from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs_single as single
from ipfs_datasets_py.logic.formalization.autoencoder import normative_cached_legal_ir_runtime as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import normative_legal_ir_runtime as previous
from ipfs_datasets_py.logic.formalization.autoencoder import dimension_source_inputs as bounded
from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as complete
from .test_contextual_legal_ir_runtime import loader, make_contextual, pin, repin, write
from .test_fresh_scalar_source_inputs import config, plan as source_fixture_plan


def seal(value, key, digest=fresh.digest):
    value[key] = digest({name: item for name, item in value.items() if name != key})
    return value


def synthetic_native768(plan, vectors, asset_config):
    """Typed saved observations only; never call a tokenizer or encoder."""
    rows = deepcopy(plan["source_inputs"])
    tokens = [{"input_ids": [101, 102], "attention_mask": [1, 1]} for _ in rows]
    schedule = [("complete", [0]), ("encoder", [0])]
    schedule.extend(("complete", list(range(index, min(index + 4, len(rows)))))
                    for index in range(0, len(rows), 4))
    events = []
    for index, (role, indices) in enumerate(schedule):
        events.append(dict(index=index, path=role, batch_size=len(indices), padded_width=2,
            sources=[dict(id=rows[i]["id"], source_sha256=fresh.authored.text_sha(rows[i]["source_text"]),
                active_token_count=2, token_input_sha256=original._digest([101, 102])) for i in indices],
            input_ids=[[101, 102] for _ in indices], attention_mask=[[1, 1] for _ in indices],
            actual_forward_checked=True))
    profile = complete.reference._PROFILE
    assets = dict(schema="gte-multilingual-local-assets-receipt/v1", status="available",
        profile_id=complete.PROFILE_ID, manifest_sha256=asset_config["expected_manifest_sha256"],
        model_revision=profile.MODEL_REV, code_revision=profile.CODE_REV,
        model_directory=asset_config["model_directory"], code_directory=asset_config["code_directory"],
        files=[dict(relative_to=role, path=name, **deepcopy(content))
               for (role, name), content in sorted(profile.PUBLISHED_ASSETS.items())],
        model_numerics_verified=False, proof_authority=False, unavailable_reasons=[])
    # Names are explicit synthetic metadata. The native binding verifier is
    # replaced for the fixture; these declarations never load a checkpoint.
    loading = dict(architecture="NewForTokenClassification", tensor_count=138,
        tensor_names=sorted(["classifier.bias", "classifier.weight"] + [f"new.synthetic.{i}" for i in range(136)]),
        classifier_loaded=True, classifier_logits_used_for_dense_embedding=False,
        missing_keys=[], unexpected_keys=[], mismatched_keys=[], error_msgs=[])
    dense = dict(encoder_and_complete_hidden_states_bitwise_equal=True, evaluation_mode=True,
        probe_tokens=2, scope="first admitted source; source used only, no targets")
    native = dict(schema="fresh-bounded-native768-production/v1", assets=assets,
        source_rows=rows, vectors=deepcopy(vectors), token_rows=tokens, forward_observations=events,
        complete_checkpoint_loading=loading, dense_path_verification=dense, implementation=complete._implementation(),
        execution_profile=dict(batch_size=4, device="cpu", dtype="float32", pooling="cls",
            normalization="l2", max_tokens_including_special_tokens=512, attention_implementation="eager"),
        historical_profile_token_limit=8192, experiment_token_limit=512, cached_profile_relabelled=False)
    native["forward_validation"] = bounded.validate_forward_observations(native)
    return native


def make_cached(tmp_path, monkeypatch, dimension=384, recipe_name="normative-wording-ce", *, unicode=False):
    """A portable synthetic cache; no encoder/optimizer or actual decoder runs."""
    data = make_contextual(tmp_path, dimension=dimension)
    data["checkpoint"]["recipe"] = deepcopy(previous._RECIPES[recipe_name])
    repin(data)
    plan = source_fixture_plan()
    if unicode:
        rows = deepcopy(plan["source_rows"])
        for row in rows:
            row["source_text"] = "\n\n".join(piece + " législation Ω" for piece in row["source_text"].split("\n\n"))
        plan = fresh.source_plan(rows, expected_source_rows_sha256=fresh.digest(rows),
                                 sealed_comparison_sha256=plan["sealed_comparison_sha256"])
    monkeypatch.setattr(fresh, "_validate_native_binding", lambda *args: None)
    producer = tmp_path / "historical-producer.py"
    producer.write_text("# Explicit synthetic historical receipt witness; never executed.\n", encoding="utf-8")
    artifact = None
    if dimension == 384:
        path = tmp_path / "source384-texts.txt"
        path.write_bytes(b"\n\n".join(row["source_text"].encode("utf-8") for row in plan["source_inputs"]) + b"\n\n")
        artifact = pin(path)
    report = dict(schema=fresh.PRODUCTION_SCHEMA, complete=True, dimension=dimension,
        plan_sha256=plan["plan_sha256"], source_rows_sha256=plan["source_rows_sha256"],
        sealed_comparison_sha256=plan["sealed_comparison_sha256"], asset_config=config(dimension),
        producer_files={str(producer): pin(producer)["sha256"]},
        producer_pin_scope="named local producers; caller freezes transitive import closure",
        vectors=[dict(id=row["id"], source_sha256=fresh.authored.text_sha(row["source_text"]),
            vector=[float(offset == index % dimension) for offset in range(dimension)],
            token_count=2, token_input_sha256=fresh.digest([101, 102]))
            for index, row in enumerate(plan["source_inputs"])],
        native_production={"diagnostic_test_double": True}, source_artifact=artifact,
        representation=runtime._representation(dimension), receipt_count=216,
        encoder_executed=True, batch_size=4, max_seconds=600, elapsed_seconds=0.,
        deadline_cooperative=True, native_forward_interruptible=False, **fresh.FALSE)
    if dimension == 768:
        report["native_production"] = synthetic_native768(plan, [row["vector"] for row in report["vectors"]], report["asset_config"])
    seal(report, "production_sha256")
    cache = single.assemble(plan, report, dimension=dimension)
    data.update(source_plan=plan, production=report, source_cache=cache, producer_path=producer,
                recipe_name=recipe_name)
    data["selected_row_ids"] = [cache["rows"][-1]["id"], cache["rows"][0]["id"], cache["rows"][12]["id"]]
    return cache_repin(data)


def cache_repin(data):
    root = data["root"]
    data["cache_pins"] = {
        "source_plan_pin": write(root / "retained-source-plan.json", data["source_plan"]),
        "production_pin": write(root / "retained-production.json", data["production"]),
        "source_cache_pin": write(root / "retained-source-cache.json", data["source_cache"]),
    }
    return data


def options(data):
    base = data["options"]
    request = dict(base["request"], decoder_contract_id=runtime.DECODER_CONTRACT_ID,
                   training_recipe_name=data["recipe_name"])
    return dict(request=request,
        checkpoint_pin=deepcopy(base["checkpoint_pin"]), preprocessing_pin=deepcopy(base["preprocessing_pin"]),
        donor_checkpoint_pin=deepcopy(base["donor_checkpoint_pin"]), **deepcopy(data["cache_pins"]),
        source_owner_pins={name: pin(path) for name, path in runtime.source_owner_paths().items()},
        row_ids=list(data["selected_row_ids"]))


def refuse(data, loader, **changes):
    kwargs = options(data)
    kwargs.update(changes)
    with pytest.raises(ValueError):
        runtime.open_normative_cached_legal_ir_autoencoder(**kwargs)
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe_name", ["normative-wording-zero", "normative-wording-ce"])
def test_prepare_separates_selected_recipe_width_and_reconstructs_only_pinned_sources(tmp_path, monkeypatch, loader, dimension, recipe_name):
    data = make_cached(tmp_path, monkeypatch, dimension, recipe_name)
    before = deepcopy(data["source_cache"])
    result = runtime.prepare_normative_cached_legal_ir_runtime(**options(data))
    assert result["schema"] == runtime.SCHEMA
    assert result["decoder_contract_id"] == "normative-retained-source-cache-legal-ir/v1"
    assert result["saved_training_recipe"] == data["checkpoint"]["recipe"]
    assert result["row_ids"] == data["selected_row_ids"]
    expected = {row["id"]: row for row in before["rows"]}
    assert result["source_inputs"]["rows"] == [expected[identifier] for identifier in data["selected_row_ids"]]
    assert all(set(row) == {"id", "source_text", "input"} for row in result["source_inputs"]["rows"])
    assert result["source_inputs"]["contexts"] == {identifier: before["source_contexts"][identifier]
                                                 for identifier in data["selected_row_ids"]}
    assert len(result["source_owner_receipts"]) == len(runtime.SOURCE_OWNER_NAMES)
    assert result["native_ir_schema_version"] is result["decoder_profile_id"] is result["decoder_format_id"] is None
    assert all(value is False for value in result["authority"].values())
    assert result["model_manager_binding_resolved"] is result["original_targets_accessed"] is False
    selector = result["model_manager_selector"]
    assert len(selector) == 10 and selector["dimension"] == dimension
    assert selector["role"] == recipe_name.replace("-", "_") + "_selected_semantic_decoder_state"
    assert selector["schema_version"] is selector["profile_id"] is selector["format_id"] is None
    assert loader["loads"] == loader["calls"] == [] and data["source_cache"] == before
    result["source_inputs"]["rows"][0]["input"][0] = 99.
    again = runtime.prepare_normative_cached_legal_ir_runtime(**options(data))
    assert again["source_inputs"]["rows"][0] == expected[data["selected_row_ids"][0]]


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe_name", ["normative-wording-zero", "normative-wording-ce"])
def test_lazy_open_passes_frozen_preprocessing_once_and_only_selected_raw_rows(tmp_path, monkeypatch, loader, dimension, recipe_name):
    data = make_cached(tmp_path, monkeypatch, dimension, recipe_name)
    # A nonidentity saved transform makes premature or duplicate preprocessing
    # observable at the actual numeric call boundary, even with an inert model.
    transform = dict(data["checkpoint"]["input_transform"], mean=[0.125] * dimension, scale=2.)
    data["checkpoint"]["input_transform"] = deepcopy(transform)
    data["preprocessing"]["input_transform"] = deepcopy(transform)
    repin(data)
    state_before = Path(data["options"]["checkpoint_pin"]["path"]).read_bytes()
    handle = runtime.open_normative_cached_legal_ir_autoencoder(**options(data))
    assert len(loader["loads"]) == 1 and not loader["calls"]
    restored = loader["loads"][0]
    assert set(restored) == {"checkpoint", "preprocessing", "donor_checkpoint"}
    assert restored["checkpoint"]["input_transform"] == data["checkpoint"]["input_transform"]
    assert restored["preprocessing"] == data["preprocessing"]
    assert set(restored["donor_checkpoint"]) == {"codec", "config", "model_state"}
    for _ in range(2):
        observed = handle.infer_cached()
        assert observed["model_inference_executed"] is True and observed["original_targets_accessed"] is False
        assert observed["runtime_selection"]["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID
        assert all(value is False for value in observed["authority"].values())
    expected = {row["id"]: row for row in data["source_cache"]["rows"]}
    assert loader["calls"][0]["source_inputs"]["rows"] == [expected[i] for i in data["selected_row_ids"]]
    assert loader["calls"][0]["options"] == {"output_cap": 512, "deadline_seconds": 120, "batch_size": 8}
    assert Path(data["options"]["checkpoint_pin"]["path"]).read_bytes() == state_before


@pytest.mark.parametrize("change", ["target_row", "target_segment", "target_cache", "extra_envelope", "reordered_rows",
    "reordered_aliases", "reordered_clauses", "paragraph_vector", "clause_vector", "byte_offset_bool", "char_offset",
    "mask_hint", "authority", "wrong_schema", "wrong_width", "bool_width", "changed_source"])
def test_rehashed_cache_corruption_refuses_before_loading(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch)
    cache = data["source_cache"]
    row = cache["rows"][0]
    segment = cache["source_contexts"][row["id"]]["segments"][0]
    if change == "target_row": row["target_ids"] = [1, 2]
    elif change == "target_segment": segment["target"] = {"rules": []}
    elif change == "target_cache": cache["clause_cache"][0]["reference"] = {}
    elif change == "extra_envelope": cache["gold"] = []
    elif change == "reordered_rows": cache["rows"] = list(reversed(cache["rows"]))
    elif change == "reordered_aliases": cache["source_aliases"] = list(reversed(cache["source_aliases"]))
    elif change == "reordered_clauses": cache["clause_cache"] = list(reversed(cache["clause_cache"]))
    elif change == "paragraph_vector": row["input"] = [float(i == 383) for i in range(384)]
    elif change == "clause_vector":
        segment["vector"] = [float(i == 383) for i in range(384)]
        segment["embedding_sha256"] = original._digest(segment["vector"])
    elif change == "byte_offset_bool": segment["byte_start"] = False
    elif change == "char_offset": segment["char_end"] += 1
    elif change == "mask_hint": row["clause_padding_mask"] = [True] * 8
    elif change == "authority": cache["qualified"] = True
    elif change == "wrong_schema": cache["schema"] = "prospective-wording-source-inputs/v1"
    elif change == "wrong_width": cache["dimension"] = 768
    elif change == "bool_width": cache["dimension"] = True
    else: row["source_text"] += " replaced"
    seal(cache, "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


@pytest.mark.parametrize("change", ["token_bool", "token_overlength", "token_digest", "vector_bool", "vector_overflow",
    "wrong_width", "receipt_bool", "batch_bool", "authority", "model_revision", "historical_profile", "actual_context"])
def test_rehashed_production_corruption_refuses_before_loading(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch)
    report = data["production"]
    item = report["vectors"][0]
    if change == "token_bool": item["token_count"] = True
    elif change == "token_overlength": item["token_count"] = 513
    elif change == "token_digest": item["token_input_sha256"] = "x" * 64
    elif change == "vector_bool": item["vector"][0] = True
    elif change == "vector_overflow": item["vector"][0] = 1e39
    elif change == "wrong_width": report["dimension"] = 768
    elif change == "receipt_bool": report["receipt_count"] = True
    elif change == "batch_bool": report["batch_size"] = True
    elif change == "authority": report["transforms_fitted"] = True
    elif change == "model_revision": report["representation"]["revision"] = "f" * 40
    elif change == "historical_profile": report["representation"]["historical_profile_token_limit"] = 512
    else: report["representation"]["experiment_token_limit"] = 8192
    seal(report, "production_sha256")
    data["source_cache"]["production_sha256"] = report["production_sha256"]
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


@pytest.mark.parametrize("field,value", [("decoder_contract_id", previous.DECODER_CONTRACT_ID),
    ("training_recipe_name", "normative-aux025"), ("dimension", True), ("dimension", 8), ("dimension", 786),
    ("ir_family_id", "intent_ir"), ("task_id", "legal_text_reconstruction"), ("dimension_role", "latent")])
def test_wrong_request_is_rejected_before_artifact_reads(tmp_path, monkeypatch, loader, field, value):
    data = make_cached(tmp_path, monkeypatch)
    kwargs = options(data)
    kwargs["request"][field] = value
    monkeypatch.setattr(original, "_read", lambda *args, **kw: pytest.fail("invalid request read an asset"))
    with pytest.raises(ValueError):
        runtime.open_normative_cached_legal_ir_autoencoder(**kwargs)
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("change", ["alias_role", "false_selected", "wrong_recipe", "donor_lineage", "frozen_transform"])
def test_original_state_donor_and_preprocessing_gates_remain_required(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch)
    if change == "alias_role": data["checkpoint"]["role"] = "last-attempt"
    elif change == "false_selected": data["checkpoint"]["selected"] = False
    elif change == "wrong_recipe": data["checkpoint"]["recipe"]["weight"] = 0.025
    elif change == "donor_lineage": data["checkpoint"]["lineage"]["teacher_checkpoint_sha256"] = "f" * 64
    else: data["preprocessing"]["input_transform"] = dict(data["preprocessing"]["input_transform"], scale=2.)
    repin(data)
    refuse(data, loader)


def test_original_runtime_rejects_foreign_cached_sources_without_changing_its_recipe_gate(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="selected recipe"):
        original.prepare_contextual_legal_ir_runtime(**data["options"])
    kwargs = deepcopy(data["options"])
    kwargs["request"].update(decoder_contract_id=previous.DECODER_CONTRACT_ID,
                             training_recipe_name=data["recipe_name"])
    kwargs["source_owner_pins"].update({name: pin(path) for name, path in runtime.source_owner_paths().items()
                                     if name in previous.SOURCE_OWNER_NAMES})
    kwargs["source_inputs_pin"] = write(data["root"] / "foreign-rows.json", data["source_cache"]["rows"])
    kwargs["source_contexts_pin"] = write(data["root"] / "foreign-contexts.json", data["source_cache"]["source_contexts"])
    kwargs["row_ids"] = list(data["selected_row_ids"])
    with pytest.raises(ValueError, match="saved original"):
        previous.prepare_normative_legal_ir_runtime(**kwargs)
    assert loader["loads"] == loader["calls"] == []


def test_historical_hardlinks_are_observed_without_import_or_authority(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch)
    os.link(data["producer_path"], tmp_path / "same-historical-producer.py")
    assert data["producer_path"].stat().st_nlink == 2
    result = runtime.prepare_normative_cached_legal_ir_runtime(**options(data))
    assert all(value is False for value in result["authority"].values())
    assert loader["loads"] == loader["calls"] == []
    handle = runtime.open_normative_cached_legal_ir_autoencoder(**options(data))
    assert handle.describe()["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID
    assert len(loader["loads"]) == 1 and not loader["calls"]


@pytest.mark.parametrize("boundary", ["after_load", "before_infer", "after_infer"])
def test_historical_linked_producer_drift_refuses_at_each_endpoint(tmp_path, monkeypatch, loader, boundary):
    data = make_cached(tmp_path, monkeypatch)
    alias = tmp_path / "historical-alias.py"
    os.link(data["producer_path"], alias)
    def mutate():
        alias.write_text("# Modified only this private hardlinked fixture.\n", encoding="utf-8")
    if boundary == "after_load":
        loader["after_load"] = mutate
        with pytest.raises(ValueError) as caught:
            runtime.open_normative_cached_legal_ir_autoencoder(**options(data))
        assert caught.value.model_load_performed is True
        assert caught.value.model_inference_executed is False
    else:
        handle = runtime.open_normative_cached_legal_ir_autoencoder(**options(data))
        if boundary == "before_infer": mutate()
        else: loader["after_infer"] = mutate
        with pytest.raises(ValueError) as caught:
            handle.infer_cached()
        assert caught.value.model_inference_executed is (boundary == "after_infer")
        if boundary == "after_infer":
            assert caught.value.raw_candidate_report["scope"] == "inert boundary observation"
    assert len(loader["calls"]) == int(boundary == "after_infer")


@pytest.mark.parametrize("owner_name", ["fresh_scalar_source_inputs", "fresh_scalar_source_inputs_single", "ir_model_manager_import"])
def test_foreign_loaded_helpers_refuse_before_using_their_functions(tmp_path, monkeypatch, loader, owner_name):
    data = make_cached(tmp_path, monkeypatch)
    kwargs = options(data)
    from ipfs_datasets_py.logic.formalization.autoencoder import ir_model_manager_import as registration
    helper = {"fresh_scalar_source_inputs": fresh, "fresh_scalar_source_inputs_single": single,
              "ir_model_manager_import": registration}[owner_name]
    monkeypatch.setattr(helper, "__file__", "/foreign-worktree/" + owner_name + ".py")
    name = {"fresh_scalar_source_inputs": "_plan", "fresh_scalar_source_inputs_single": "assemble",
            "ir_model_manager_import": "ir_model_asset_record_id"}[owner_name]
    monkeypatch.setattr(helper, name, lambda *args, **kw: pytest.fail("foreign helper executed"))
    with pytest.raises(ValueError, match="origin"):
        runtime.prepare_normative_cached_legal_ir_runtime(**kwargs)
    assert loader["loads"] == loader["calls"] == []


def test_unicode_producer_digest_and_clause_offsets_keep_distinct_hash_conventions(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch, unicode=True)
    cache = data["source_cache"]
    assert fresh.digest(data["source_plan"]["source_rows"]) != original._digest(data["source_plan"]["source_rows"])
    result = runtime.prepare_normative_cached_legal_ir_runtime(**options(data))
    for row in result["source_inputs"]["rows"]:
        segments = result["source_inputs"]["contexts"][row["id"]]["segments"]
        for segment in segments:
            assert row["source_text"][segment["char_start"]:segment["char_end"]] == segment["source_text"]
            assert row["source_text"].encode()[segment["byte_start"]:segment["byte_end"]].decode() == segment["source_text"]
            assert segment["byte_end"] > segment["char_end"]
    assert cache["inputs_sha256"] == fresh.digest({k: v for k, v in cache.items() if k != "inputs_sha256"})
    assert loader["loads"] == loader["calls"] == []


def test_wrong_unicode_envelope_digest_is_not_repaired(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch, unicode=True)
    seal(data["source_cache"], "inputs_sha256", digest=original._digest)
    cache_repin(data)
    refuse(data, loader)


@pytest.mark.parametrize("change", ["paragraph_float", "clause_float", "alias_slot_bool", "encoder_tokens_float"])
def test_typed_source_plan_rejects_values_that_python_equality_would_alias(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch)
    plan = data["source_plan"]
    if change == "paragraph_float": plan["paragraph_count"] = 48.0
    elif change == "clause_float": plan["clause_occurrences"] = 180.0
    elif change == "alias_slot_bool": plan["source_aliases"][1]["slot"] = False
    else: plan["encoder_context_tokens"] = 512.0
    seal(plan, "plan_sha256")
    data["production"]["plan_sha256"] = plan["plan_sha256"]
    seal(data["production"], "production_sha256")
    data["source_cache"].update(source_plan_sha256=plan["plan_sha256"],
                                production_sha256=data["production"]["production_sha256"])
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


def test_foreign_dynamic_profile_origin_refuses_before_cache_assembly(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch, dimension=768)
    kwargs = options(data)
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768 as reference
    monkeypatch.setattr(reference._PROFILE, "__file__", "/foreign-worktree/gte_multilingual_profile.py")
    monkeypatch.setattr(single, "assemble", lambda *args, **kw: pytest.fail("foreign dynamic profile reached assembly"))
    with pytest.raises(ValueError, match="origin"):
        runtime.prepare_normative_cached_legal_ir_runtime(**kwargs)
    assert loader["loads"] == loader["calls"] == []


def test_hub_gateways_preserve_opt_in_source_contract_and_lazy_model_boundary(tmp_path, monkeypatch, loader):
    from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
    data = make_cached(tmp_path, monkeypatch)
    result = hub.prepare_normative_cached_legal_ir_runtime(**options(data))
    assert result["schema"] == runtime.SCHEMA and loader["loads"] == loader["calls"] == []
    handle = hub.open_normative_cached_legal_ir_autoencoder(**options(data))
    assert handle.describe()["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID
    assert len(loader["loads"]) == 1 and not loader["calls"]


@pytest.mark.parametrize("key", ["target_ids", "targets", "gold", "reference_rows", "references", "teacher_logits", "teacher_predictions"])
def test_targets_in_native_receipt_metadata_are_rejected_before_any_model(tmp_path, monkeypatch, loader, key):
    data = make_cached(tmp_path, monkeypatch)
    data["production"]["native_production"][key] = [1, 2]
    seal(data["production"], "production_sha256")
    data["source_cache"]["production_sha256"] = data["production"]["production_sha256"]
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


@pytest.mark.parametrize("change", ["device", "dtype", "pooling", "historical_tokens", "actual_tokens", "relabelled",
    "mask_bool", "active_count_float", "forward_proof_int", "forward_mask_bool", "extra_target", "implementation"])
def test_native768_rehashed_record_keeps_exact_execution_types_and_profile(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch, dimension=768)
    native = data["production"]["native_production"]
    if change == "device": native["execution_profile"]["device"] = "cuda"
    elif change == "dtype": native["execution_profile"]["dtype"] = "float16"
    elif change == "pooling": native["execution_profile"]["pooling"] = "mean"
    elif change == "historical_tokens": native["historical_profile_token_limit"] = 512
    elif change == "actual_tokens": native["experiment_token_limit"] = 8192
    elif change == "relabelled": native["cached_profile_relabelled"] = 0
    elif change == "mask_bool": native["token_rows"][0]["attention_mask"] = [True, True]
    elif change == "active_count_float": native["forward_observations"][0]["sources"][0]["active_token_count"] = 2.0
    elif change == "forward_proof_int": native["forward_validation"]["proof_authority"] = 0
    elif change == "forward_mask_bool": native["forward_observations"][0]["attention_mask"][0][0] = True
    elif change == "extra_target": native["target_ids"] = [1, 2]
    else: native["implementation"]["complete_loader"] = "f" * 64
    seal(data["production"], "production_sha256")
    data["source_cache"]["production_sha256"] = data["production"]["production_sha256"]
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


@pytest.mark.parametrize("name", ["autoencoder_embedding_runtime", "autoencoder_embedding_production",
                                 "autoencoder_corpus_manifest", "autoencoder_training_worker"])
def test_foreign_loaded_optimizer_dependency_origin_is_not_treated_as_current(tmp_path, monkeypatch, loader, name):
    data = make_cached(tmp_path, monkeypatch)
    kwargs = options(data)
    module = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name)
    monkeypatch.setattr(module, "__file__", "/foreign-worktree/" + name + ".py")
    with pytest.raises(ValueError, match="origin"):
        runtime.prepare_normative_cached_legal_ir_runtime(**kwargs)
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("change", ["profile", "model_revision", "code_revision", "model_directory", "missing_keys",
    "dense_eval", "classifier_not_loaded", "classifier_logits", "tensor_count_bool", "asset_bytes_bool",
    "asset_path", "asset_hash", "asset_bytes"])
def test_native768_saved_asset_loading_and_dense_observations_are_not_interchangeable(tmp_path, monkeypatch, loader, change):
    data = make_cached(tmp_path, monkeypatch, dimension=768)
    native = data["production"]["native_production"]
    if change == "profile": native["assets"]["profile_id"] = "foreign-profile"
    elif change == "model_revision": native["assets"]["model_revision"] = "f" * 40
    elif change == "code_revision": native["assets"]["code_revision"] = "f" * 40
    elif change == "model_directory": native["assets"]["model_directory"] = "/foreign/model"
    elif change == "missing_keys": native["complete_checkpoint_loading"]["missing_keys"] = ["classifier.weight"]
    elif change == "dense_eval": native["dense_path_verification"]["evaluation_mode"] = False
    elif change == "classifier_not_loaded": native["complete_checkpoint_loading"]["classifier_loaded"] = False
    elif change == "classifier_logits": native["complete_checkpoint_loading"]["classifier_logits_used_for_dense_embedding"] = True
    elif change == "tensor_count_bool": native["complete_checkpoint_loading"]["tensor_count"] = True
    elif change == "asset_bytes_bool": native["assets"]["files"][0]["bytes"] = True
    elif change == "asset_path": native["assets"]["files"][0]["path"] = "foreign.py"
    elif change == "asset_hash": native["assets"]["files"][0]["sha256"] = "f" * 64
    else: native["assets"]["files"][0]["bytes"] += 1
    seal(data["production"], "production_sha256")
    data["source_cache"]["production_sha256"] = data["production"]["production_sha256"]
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    refuse(data, loader)


def test_metadata_closing_historical_fence_cannot_hide_later_checkpoint_drift(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch)
    kwargs = options(data)
    original_fence = runtime._historical_fence
    calls = []
    def mutate_after_last_historical_fence(captured):
        original_fence(captured)
        calls.append(None)
        if len(calls) == 2:
            Path(data["options"]["checkpoint_pin"]["path"]).write_bytes(b"{}")
    monkeypatch.setattr(runtime, "_historical_fence", mutate_after_last_historical_fence)
    with pytest.raises(ValueError):
        runtime.prepare_normative_cached_legal_ir_runtime(**kwargs)
    assert len(calls) >= 2 and loader["loads"] == loader["calls"] == []


def test_last_historical_recheck_cannot_start_inference_after_checkpoint_drift(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch)
    handle = runtime.open_normative_cached_legal_ir_autoencoder(**options(data))
    original_fence = runtime._historical_fence
    calls = []
    def mutate_after_last_historical_fence(captured):
        original_fence(captured)
        calls.append(None)
        if len(calls) == 3:
            Path(data["options"]["checkpoint_pin"]["path"]).write_bytes(b"{}")
    monkeypatch.setattr(runtime, "_historical_fence", mutate_after_last_historical_fence)
    with pytest.raises(ValueError) as caught:
        handle.infer_cached()
    assert len(calls) >= 3
    assert caught.value.model_load_performed is True and caught.value.model_inference_started is False
    assert caught.value.model_inference_executed is False and loader["calls"] == []


def test_metadata_only_native_refusal_uses_exported_error_with_all_call_flags_false(tmp_path, monkeypatch, loader):
    data = make_cached(tmp_path, monkeypatch)
    data["production"]["vectors"][0]["vector"][0] = 2.
    seal(data["production"], "production_sha256")
    data["source_cache"]["production_sha256"] = data["production"]["production_sha256"]
    seal(data["source_cache"], "inputs_sha256")
    cache_repin(data)
    with pytest.raises(runtime.NormativeCachedLegalRuntimeError) as caught:
        runtime.prepare_normative_cached_legal_ir_runtime(**options(data))
    assert caught.value.model_load_started is caught.value.model_load_performed is False
    assert caught.value.model_inference_started is caught.value.model_inference_executed is False
    assert caught.value.raw_candidate_report is None and loader["loads"] == loader["calls"] == []

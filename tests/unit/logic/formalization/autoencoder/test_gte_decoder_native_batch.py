"""Synthetic cached-native joins, with genuine closed donor/replay contracts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_native_batch.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_native_batch_test_subject", PATH)


def _decoder_native_fixture(tmp_path_factory):
    """Build authenticated synthetic donors, full180/60 archives and real replay."""
    fixture_module = read_module("gte_native_original_fixture", Path(__file__).with_name("test_gte_decoder_transfer_batch.py"))
    fixture = fixture_module.decoder_transfer_fixture(tmp_path_factory)
    validation, manifest = [], []
    for index in range(60):
        row = deepcopy(fixture.primary_archive["rows"][index])
        source = "Synthetic separate validation source " + str(index)
        vector = [0.] * 384
        vector[180 + index] = 1.
        row.update(id="validation:" + str(index).zfill(3), source_text=source,
                   source_sha256=hashlib.sha256(source.encode()).hexdigest(), split="validation",
                   group_id="validation-group:" + str(index), embedding=vector,
                   embedding_sha256=subject._BATCH.digest(vector))
        validation.append(row)
        manifest.append({"id": row["id"], "source_sha256": row["source_sha256"],
            "normalized_source_sha256": hashlib.sha256(source.casefold().encode()).hexdigest(),
            "embedding_sha256": row["embedding_sha256"], "target_sha256": subject._BATCH.digest(row["target"])})
    fixture.primary_validation_archive = {"rows": validation,
        "source_embeddings": deepcopy(fixture.primary_archive["source_embeddings"])}
    fixture.primary_checkpoint["validation_manifest"] = manifest
    fixture.primary_checkpoint["training"]["selected_validation"]["count"] = 60
    fixture.primary_path.write_bytes(subject._BATCH._raw(fixture.primary_checkpoint))
    _, fixture.initialization = subject._BATCH._REUSE.create_dual_decoder(fixture.primary_path, fixture.legacy8_path,
        expected_teacher384_sha256=hashlib.sha256(fixture.primary_path.read_bytes()).hexdigest(),
        expected_legacy8_sha256=hashlib.sha256(fixture.legacy8_path.read_bytes()).hexdigest(),
        repository_root=ROOT, legacy_implementation_root=ROOT)
    fixture.donor_pins = fixture.initialization["donor_pins"]
    fixture.batch = fixture_module.prepare(fixture)
    fixture.replay = subject._REPLAY.export_decoder_transfer_batch(fixture.initialization, fixture.batch,
        expected_donor_pins=fixture.donor_pins, primary_checkpoint=fixture.primary_checkpoint,
        legacy8_checkpoint=fixture.legacy8_checkpoint)
    fixture.asset_manifest_sha256 = "b" * 64
    fixture.empty_plan = prepare(fixture)
    fixture.receipts_768 = selected_receipts(fixture.empty_plan)
    fixture.plan = prepare(fixture, receipts_768=fixture.receipts_768)
    return fixture


def decoder_native_fixture(tmp_path_factory):
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        return _decoder_native_fixture(tmp_path_factory)
    finally:
        torch.set_num_threads(previous)


native_fixture = decoder_native_fixture


def receipt(task, index=0):
    """An explicitly synthetic contract fixture; never production producer evidence."""
    vector = [0.] * 768
    vector[index % 768] = 1.
    return {"schema": subject._CORPUS.RECEIPT_SCHEMA, "id": task["id"], "source_sha256": task["source_sha256"],
        "profile_id": subject.PROFILE_ID, "dimension": 768, "embedding": vector,
        "token_count_including_special_tokens": 17, "token_input_sha256": "a" * 64,
        "truncated": False, "normalized": True, "asset_manifest_sha256": "b" * 64}


def selected_receipts(plan):
    identifiers = {row["embedding_task_id"] for head in plan["heads"].values() for row in head["missing_rows"]}
    return [receipt(task, index) for index, task in enumerate(plan["task_manifest"]["tasks"]) if task["id"] in identifiers]


def prepare(fixture, **changes):
    kwargs = {"expected_donor_pins": fixture.donor_pins, "primary_training_archive": fixture.primary_archive,
        "primary_validation_archive": fixture.primary_validation_archive, "legacy8_inputs": fixture.legacy8_inputs,
        "receipts_768": [], "expected_asset_manifest_sha256": fixture.asset_manifest_sha256}
    kwargs.update(changes)
    return subject.prepare_decoder_native_batch(fixture.initialization, fixture.batch, fixture.replay, **kwargs)


def inspect(fixture, plan=None):
    return subject.inspect_decoder_native_batch(plan if plan is not None else fixture.plan,
        fixture.initialization, fixture.batch, fixture.replay, expected_donor_pins=fixture.donor_pins)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return decoder_native_fixture(tmp_path_factory)


def test_full_original_cohort_is_audited_before_source_only_tasks(fixture):
    plan = fixture.empty_plan
    assert plan["status"] == "unavailable"
    assert plan["audit"]["input_row_count"] == 242
    assert plan["audit"]["split_counts"] == {"train": 182, "validation": 60, "test": 0, "canary": 0}
    assert plan["audit"]["quarantined_row_count"] == 0
    assert plan["task_manifest"]["task_count"] == 242
    assert plan["cache_reuse"]["missing_task_count"] == 242
    assert plan["missing_row_count"] == 18
    assert plan["native768_inputs_joined"] is False
    for task in plan["cache_reuse"]["missing_tasks"]:
        assert set(task) == {"id", "source_text", "source_sha256", "metadata"}
        assert "embedding" not in task and "reference_target" not in task
    assert all(row["embedding"] is None for row in plan["audit_rows"][-2:])
    assert inspect(fixture, plan)["ready_row_count"] == 0


def test_selected_ready_is_distinct_from_full_validation_cache_coverage(fixture):
    plan = fixture.plan
    assert plan["status"] == "ready"
    assert plan["ready_row_count"] == plan["selected_row_count"] == 18
    assert plan["cache_reuse"]["status"] == "partial"
    assert plan["cache_reuse"]["cached_receipt_count"] == 18
    assert plan["cache_reuse"]["missing_task_count"] == 224
    assert all(row["embedding_task"]["metadata"]["split"] == "train"
               for head in plan["heads"].values() for row in head["rows"])
    assert inspect(fixture)["full_missing_task_count"] == 224


def test_ready_rows_keep_exact_old_inputs_prefixes_and_teacher_targets(fixture):
    for name, head in fixture.plan["heads"].items():
        for row, original, target in zip(head["rows"], fixture.batch["heads"][name]["rows"], fixture.replay["heads"][name]["rows"]):
            for key in original:
                assert row[key] == original[key]
            assert row["teacher_logits"] == target["teacher_logits"]
            assert row["teacher_logits_sha256"] == target["teacher_logits_sha256"]
            assert row["teacher_replay_row_sha256"] == subject._REPLAY.digest(target)
            assert len(row["native_receipt"]["embedding"]) == 768
            assert row["native_receipt"]["source_sha256"] == row["source_sha256"]
            assert not any(row["kd_token_mask"])
    for key in ("producer_execution_authenticated", "archive_authenticity_verified", "teacher_qualified",
                "production_kd_eligible", "training_executed", "distillation_executed", "encoder_inference_executed"):
        assert fixture.plan[key] is False


def test_one_cached_row_gives_partial_without_remapping(fixture):
    plan = prepare(fixture, receipts_768=fixture.receipts_768[:1])
    assert plan["status"] == "partial"
    assert plan["ready_row_count"] == 1 and plan["missing_row_count"] == 17
    assert inspect(fixture, plan)["full_cached_receipt_count"] == 1


def test_complete_source_cache_does_not_train_on_validation(fixture):
    cached = [receipt(task, index) for index, task in enumerate(fixture.empty_plan["task_manifest"]["tasks"])]
    plan = prepare(fixture, receipts_768=cached)
    assert plan["status"] == "ready" and plan["cache_reuse"]["status"] == "ready"
    assert plan["cache_reuse"]["cached_receipt_count"] == 242
    assert sum(head["ready_row_count"] for head in plan["heads"].values()) == 18
    assert inspect(fixture, plan)["full_missing_task_count"] == 0


def test_cross_split_group_quarantines_selected_row_without_replacement(fixture):
    archive = deepcopy(fixture.primary_validation_archive)
    archive["rows"][0]["group_id"] = fixture.primary_archive["rows"][0]["group_id"]
    plan = prepare(fixture, primary_validation_archive=archive)
    assert plan["audit"]["quarantined_row_count"] == 2
    assert plan["quarantined_row_count"] == 1
    assert plan["heads"]["primary384"]["selected_row_count"] == 16
    assert plan["heads"]["primary384"]["quarantined_rows"][0]["id"] == "training:000"
    assert plan["heads"]["primary384"]["quarantined_rows"][0]["reasons"] == ["cross_split_connected_component"]
    assert plan["task_manifest"]["rejected_row_count"] == 2
    assert plan["task_manifest"]["task_count"] == 240
    assert inspect(fixture, plan)["quarantined_row_count"] == 1


def test_normalized_source_leakage_is_checked_outside_selected_subset(fixture):
    archive = deepcopy(fixture.primary_validation_archive)
    row = archive["rows"][-1]
    source = fixture.primary_archive["rows"][-1]["source_text"].upper() + "  "
    row["source_text"] = source
    row["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    plan = prepare(fixture, primary_validation_archive=archive)
    assert plan["audit"]["quarantined_row_count"] == 2
    assert plan["task_manifest"]["rejected_row_count"] == 2
    assert plan["quarantined_row_count"] == 0


@pytest.mark.parametrize("mutation", ["last_training_source", "last_training_vector", "last_training_target",
    "validation_count", "validation_vector", "validation_digest", "validation_split", "provenance", "extra_field"])
def test_complete_archives_are_checked_before_selected_native_join(fixture, mutation):
    train, validation = deepcopy(fixture.primary_archive), deepcopy(fixture.primary_validation_archive)
    if mutation == "last_training_source": train["rows"][-1]["source_text"] += "changed"
    elif mutation == "last_training_vector": train["rows"][-1]["embedding"][0] += .1
    elif mutation == "last_training_target": train["rows"][-1]["target"]["rules"][0]["object"] = "new-object"
    elif mutation == "validation_count": validation["rows"].pop()
    elif mutation == "validation_vector": validation["rows"][-1]["embedding"][0] += .1
    elif mutation == "validation_digest": validation["rows"][-1]["source_sha256"] = "d" * 64
    elif mutation == "validation_split": validation["rows"][-1]["split"] = "test"
    elif mutation == "provenance": validation["source_embeddings"]["revision"] = "d" * 40
    elif mutation == "extra_field": validation["rows"][-1]["invented"] = False
    with pytest.raises(ValueError):
        prepare(fixture, primary_training_archive=train, primary_validation_archive=validation)


@pytest.mark.parametrize("mutation", ["source", "raw_vector", "reference", "profile", "modal_id", "count"])
def test_legacy_cache_and_full_raw_latent_manifest_are_bound(fixture, mutation):
    inputs = deepcopy(fixture.legacy8_inputs)
    if mutation == "source": inputs[-1]["text"] += "changed"
    elif mutation == "raw_vector": inputs[-1]["embedding_vector"][0] += .01
    elif mutation == "reference": inputs[-1]["modal_ir"]["formulas"][0]["predicate"]["arguments"][1] = "reports"
    elif mutation == "profile": inputs[-1]["embedding_model"] = "linguistic-feature-cache"
    elif mutation == "modal_id": inputs[-1]["modal_ir"]["document_id"] = "different-core-source"
    elif mutation == "count": inputs.pop()
    with pytest.raises(ValueError):
        prepare(fixture, legacy8_inputs=inputs)


@pytest.mark.parametrize("mutation", ["id", "source", "profile", "dimension", "width", "asset", "tokens",
    "token_bool", "truncated", "normalization", "nan", "bool_vector", "duplicate", "extra_field"])
def test_incompatible_cached_native_receipts_fail_whole_admission(fixture, mutation):
    cached = deepcopy(fixture.receipts_768)
    row = cached[-1]
    if mutation == "id": row["id"] = "gte768:invented"
    elif mutation == "source": row["source_sha256"] = "c" * 64
    elif mutation == "profile": row["profile_id"] = "old384-profile"
    elif mutation == "dimension": row["dimension"] = 384
    elif mutation == "width": row["embedding"] = [1.] + [0.] * 383
    elif mutation == "asset": row["asset_manifest_sha256"] = "c" * 64
    elif mutation == "tokens": row["token_count_including_special_tokens"] = 8193
    elif mutation == "token_bool": row["token_count_including_special_tokens"] = True
    elif mutation == "truncated": row["truncated"] = True
    elif mutation == "normalization": row["normalized"] = False
    elif mutation == "nan": row["embedding"][0] = float("nan")
    elif mutation == "bool_vector": row["embedding"][0] = True
    elif mutation == "duplicate": cached.append(deepcopy(row))
    elif mutation == "extra_field": row["producer_authenticated"] = True
    with pytest.raises(ValueError):
        prepare(fixture, receipts_768=cached)


def test_receipt_for_quarantined_source_is_not_silently_admitted(fixture):
    archive = deepcopy(fixture.primary_validation_archive)
    archive["rows"][0]["group_id"] = fixture.primary_archive["rows"][0]["group_id"]
    with pytest.raises(ValueError, match="unexpected task"):
        prepare(fixture, primary_validation_archive=archive, receipts_768=fixture.receipts_768)


@pytest.mark.parametrize("mutation", ["schema", "status", "plan_digest", "batch_digest", "replay_digest", "pins",
    "profile", "manifest", "audit_flag", "audit_count", "audit_rows_group", "audit_rows_source", "task_source",
    "task_count", "cache_missing", "cache_flags", "native_vector", "teacher_logits", "reference_prefix",
    "next_bool", "native_row_digest", "head_count", "head_dimension", "flags", "flag_integer", "extra_top"])
def test_inspection_reconstructs_all_bound_fields_even_if_outer_digest_is_resigned(fixture, mutation):
    plan = deepcopy(fixture.plan)
    if mutation == "schema": plan["schema"] = "invented"
    elif mutation == "status": plan["status"] = "partial"
    elif mutation == "plan_digest": plan["plan_sha256"] = "d" * 64
    elif mutation == "batch_digest": plan["batch_sha256"] = "d" * 64
    elif mutation == "replay_digest": plan["replay_sha256"] = "d" * 64
    elif mutation == "pins": plan["donor_pins"]["teacher384_weights_sha256"] = "d" * 64
    elif mutation == "profile": plan["profile_id"] = "invented"
    elif mutation == "manifest": plan["source_manifest_bindings"]["primary_training_manifest_sha256"] = "d" * 64
    elif mutation == "audit_flag": plan["audit"]["vectors_producer_verified"] = True
    elif mutation == "audit_count": plan["audit"]["input_row_count"] = 18
    elif mutation == "audit_rows_group": plan["audit_rows"][-3]["group_id"] = "repartitioned"
    elif mutation == "audit_rows_source": plan["audit_rows"][0]["source_text"] += "changed"
    elif mutation == "task_source": plan["task_manifest"]["tasks"][0]["source_text"] += "changed"
    elif mutation == "task_count": plan["task_manifest"]["task_count"] = 18
    elif mutation == "cache_missing": plan["cache_reuse"]["missing_tasks"].pop()
    elif mutation == "cache_flags": plan["cache_reuse"]["producer_execution_authenticated"] = True
    elif mutation == "native_vector": plan["heads"]["primary384"]["rows"][0]["native_receipt"]["embedding"][0] += .01
    elif mutation == "teacher_logits": plan["heads"]["primary384"]["rows"][0]["teacher_logits"][0][0] += .01
    elif mutation == "reference_prefix": plan["heads"]["legacy8"]["rows"][0]["prefix_ids"][1] = 4
    elif mutation == "next_bool": plan["heads"]["primary384"]["rows"][0]["next_token_ids"][0] = True
    elif mutation == "native_row_digest": plan["heads"]["primary384"]["rows"][0]["native_row_sha256"] = "d" * 64
    elif mutation == "head_count": plan["heads"]["primary384"]["ready_row_count"] = True
    elif mutation == "head_dimension": plan["heads"]["legacy8"]["donor_input_dimension"] = 384
    elif mutation == "flags": plan["production_kd_eligible"] = True
    elif mutation == "flag_integer": plan["native768_inputs_joined"] = 1
    elif mutation == "extra_top": plan["invented"] = False
    if mutation != "plan_digest":
        plan["plan_sha256"] = subject.digest({key: value for key, value in plan.items() if key != "plan_sha256"})
    with pytest.raises(ValueError):
        inspect(fixture, plan)


@pytest.mark.parametrize("asset", [None, "a", "B" * 64, True])
def test_selected_asset_generation_is_required_even_when_cache_empty(fixture, asset):
    with pytest.raises(ValueError):
        prepare(fixture, expected_asset_manifest_sha256=asset)


def test_returned_objects_do_not_alias_archives_receipts_or_saved_prefixes(fixture):
    originals = deepcopy((fixture.primary_archive, fixture.primary_validation_archive, fixture.legacy8_inputs,
                          fixture.receipts_768, fixture.batch, fixture.replay))
    plan = prepare(fixture, receipts_768=fixture.receipts_768)
    plan["audit_rows"][0]["embedding"][0] += 1.
    plan["heads"]["primary384"]["rows"][0]["teacher_logits"][0][0] += 1.
    plan["cache_reuse"]["reused_receipts"][0]["embedding"][0] += 1.
    assert originals == (fixture.primary_archive, fixture.primary_validation_archive, fixture.legacy8_inputs,
                         fixture.receipts_768, fixture.batch, fixture.replay)


def test_native_task_bound_does_not_accept_overflow_receipt_iterable(fixture):
    def overflow():
        for _ in range(4097):
            yield fixture.receipts_768[0]
    with pytest.raises(ValueError, match="exceeds max_rows"):
        prepare(fixture, receipts_768=overflow())


def test_import_preparation_and_inspection_never_load_tensor_or_encoder_libraries(fixture, tmp_path):
    payload = {"initialization": fixture.initialization, "batch": fixture.batch, "replay": fixture.replay,
        "expected_donor_pins": fixture.donor_pins, "primary_training_archive": fixture.primary_archive,
        "primary_validation_archive": fixture.primary_validation_archive, "legacy8_inputs": fixture.legacy8_inputs,
        "receipts_768": fixture.receipts_768, "expected_asset_manifest_sha256": fixture.asset_manifest_sha256}
    path = tmp_path / "native-input.json"
    path.write_text(json.dumps(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_native',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));result=module.prepare_decoder_native_batch(**payload)
module.inspect_decoder_native_batch(result,payload['initialization'],payload['batch'],payload['replay'],expected_donor_pins=payload['expected_donor_pins'])
assert result['status']=='ready'
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)
